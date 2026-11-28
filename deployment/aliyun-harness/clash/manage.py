#!/usr/bin/env python3
"""本机代理管理：保存多份订阅配置，仅执行固定代理管理操作。"""
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import yaml

ROOT = Path('/var/lib/aihub-clash')
CONFIG = ROOT / 'config.yaml'
PROFILES = ROOT / 'profiles'
REGISTRY = ROOT / 'profiles.json'
ACTIONS = ('status', 'subscribe', 'mode', 'select', 'refresh', 'start', 'stop', 'profiles', 'activate', 'delete', 'rename')


class PublicError(Exception):
    """可安全显示给用户的提示，禁止拼接订阅或底层异常。"""


def write_private(path, content, core=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(content)
    temporary.chmod(0o600)
    if core:
        owner = pwd.getpwnam('aihub-clash')
        os.chown(temporary, owner.pw_uid, owner.pw_gid)
    temporary.replace(path)


def api(path, method='GET', data=None):
    config = yaml.safe_load(CONFIG.read_text())
    request = urllib.request.Request('http://127.0.0.1:9090' + path,
        headers={'Authorization': 'Bearer ' + config['secret'], 'Content-Type': 'application/json'},
        data=json.dumps(data).encode() if data is not None else None, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read()
        return json.loads(body) if body else {}


def registry():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text())
    return {'active': None, 'items': []}


def save_registry(data):
    write_private(REGISTRY, json.dumps(data, ensure_ascii=False))


def find_profile(store, identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise PublicError('配置标识不正确。')
    for item in store['items']:
        if item['id'] == identifier:
            return item
    raise PublicError('找不到这份配置，请刷新列表。')


def validate_url(url):
    if not isinstance(url, str):
        raise PublicError('订阅链接格式不正确。')
    url = url.strip()
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    if not valid or len(url) > 4096:
        raise PublicError('请填写完整的 HTTPS Clash／Mihomo 订阅地址。')
    return url


def parse_subscription(content):
    if len(content) > 8 * 1024 * 1024:
        raise PublicError('订阅超过 8 MB，无法导入。')
    try:
        value = yaml.safe_load(content)
    except (yaml.YAMLError, UnicodeError):
        raise PublicError('订阅不是 Clash／Mihomo YAML 格式，请复制 Clash 专用订阅。') from None
    if not isinstance(value, dict) or not isinstance(value.get('proxies'), list) or not value['proxies']:
        raise PublicError('订阅缺少 Clash 节点，请复制 Clash 专用订阅。')
    if value.get('proxy-providers') or value.get('rule-providers'):
        raise PublicError('暂不支持引用其他文件或远程提供者的配置，请使用包含完整节点和规则的订阅。')
    # 不允许订阅改变监听、控制密钥、TUN、脚本或服务器文件路径。
    return {key: value[key] for key in ('proxies', 'proxy-groups', 'rules') if key in value}


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'clash-verge/v2.5.2', 'Accept': '*/*'})
    errors = []
    # 有可用节点后，可经当前代理更新订阅；首次导入仍可尝试直连。
    running = subprocess.run(['systemctl', 'is-active', '--quiet', 'aihub-clash']).returncode == 0
    routes = [True, False] if running else [False]
    for use_proxy in routes:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': 'http://127.0.0.1:7890'} if use_proxy else {}))
        try:
            with opener.open(request, timeout=18) as response:
                return parse_subscription(response.read(8 * 1024 * 1024 + 1))
        except PublicError:
            raise
        except urllib.error.HTTPError as error:
            errors.append('订阅下载失败：服务商返回 HTTP ' + str(error.code) + '。')
        except (TimeoutError, socket.timeout):
            errors.append('订阅下载超时：云服务器无法及时连接订阅站。')
        except urllib.error.URLError as error:
            errors.append('订阅下载失败：HTTPS 证书验证失败。' if isinstance(error.reason, ssl.SSLError) else '订阅下载失败：云服务器无法连接订阅站。')
    raise PublicError(errors[-1] + ' 已保留原配置，可在有可用代理节点后重试。')


def compose(subscription):
    current = yaml.safe_load(CONFIG.read_text())
    groups = subscription.get('proxy-groups') or []
    node_names = [node.get('name') for node in subscription['proxies'] if isinstance(node, dict) and isinstance(node.get('name'), str)]
    targets = [group.get('name') for group in groups if isinstance(group, dict) and isinstance(group.get('name'), str)]
    if not groups:
        groups = [{'name': 'Proxy', 'type': 'select', 'proxies': node_names + ['DIRECT']}]
    # 保留服务商节点、策略组和规则，代理入口由服务器固定管理。
    return {'mixed-port': 7890, 'allow-lan': False, 'bind-address': '127.0.0.1',
        'mode': current.get('mode', 'rule'), 'log-level': 'warning', 'external-controller': '127.0.0.1:9090',
        'secret': current['secret'], 'tun': {'enable': False}, 'profile': {'store-selected': True},
        'proxies': subscription['proxies'], 'proxy-groups': groups,
        'rules': subscription.get('rules') or ['MATCH,' + groups[0]['name']]}


def apply_subscription(subscription):
    config = compose(subscription)
    candidate = ROOT / 'candidate.yaml'
    write_private(candidate, yaml.safe_dump(config, allow_unicode=True, sort_keys=False), core=True)
    check = subprocess.run(['runuser', '-u', 'aihub-clash', '--', '/usr/bin/verge-mihomo', '-t', '-d', str(ROOT), '-f', str(candidate)], capture_output=True, timeout=50)
    if check.returncode:
        candidate.unlink(missing_ok=True)
        raise PublicError('配置校验失败，可能包含不兼容节点或缺少规则数据库；原配置仍保留。')
    previous = CONFIG.read_text()
    was_running = subprocess.run(['systemctl', 'is-active', '--quiet', 'aihub-clash']).returncode == 0
    candidate.replace(CONFIG)
    if not was_running:
        return
    try:
        subprocess.run(['systemctl', 'restart', 'aihub-clash'], check=True, capture_output=True)
        for attempt in range(15):
            try:
                api('/version')
                return
            except OSError:
                time.sleep(1)
        raise PublicError('新配置启动失败，已恢复之前配置。')
    except Exception:
        write_private(CONFIG, previous, core=True)
        subprocess.run(['systemctl', 'restart', 'aihub-clash'], capture_output=True)
        raise PublicError('新配置启动失败，已恢复之前配置。') from None


def store_subscription(store, url, name, subscription):
    existing = next((item for item in store['items'] if item['url'] == url), None)
    identifier = existing['id'] if existing else uuid.uuid4().hex
    item = {'id': identifier, 'name': name, 'url': url, 'updated': int(time.time()),
            'nodes': len(subscription['proxies']), 'groups': len(subscription.get('proxy-groups', [])),
            'rules': len(subscription.get('rules', []))}
    apply_subscription(subscription)
    write_private(PROFILES / (identifier + '.yaml'), yaml.safe_dump(subscription, allow_unicode=True, sort_keys=False))
    store['items'] = [item if value['id'] == identifier else value for value in store['items']]
    if not existing:
        store['items'].append(item)
    store['active'] = identifier
    save_registry(store)
    return item


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ACTIONS:
        raise PublicError('不允许的代理操作。')
    action = args[0]
    data = json.loads(args[1]) if len(args) == 2 else {}
    if not isinstance(data, dict):
        raise PublicError('请求格式不正确。')
    store = registry()
    if action == 'profiles':
        print(json.dumps(store, ensure_ascii=False))
        return
    if action in ('start', 'stop'):
        subprocess.run(['systemctl', 'enable' if action == 'start' else 'disable', '--now', 'aihub-clash'], check=True, capture_output=True)
        if action == 'start':
            for attempt in range(15):
                try:
                    api('/version')
                    break
                except OSError:
                    time.sleep(1)
            else:
                raise PublicError('核心启动未就绪，请检查服务状态。')
    elif action == 'status':
        config = yaml.safe_load(CONFIG.read_text())
        running = subprocess.run(['systemctl', 'is-active', '--quiet', 'aihub-clash']).returncode == 0
        result = {'running': running, 'subscribed': bool(store['active'] or config.get('proxy-providers')),
                  'proxy': 'http://127.0.0.1:7890', 'mode': config.get('mode'), 'activeProfile': store['active']}
        if running:
            runtime = api('/configs')
            runtime_proxies = api('/proxies').get('proxies', {})
            selected = runtime_proxies.get('Proxy', {})
            result['groups'] = [{'name': name, 'selected': value.get('now'), 'nodes': value.get('all', [])} for name, value in runtime_proxies.items() if value.get('type', '').lower() in ('selector', 'select') and name != 'GLOBAL']
            result.update(mode=runtime.get('mode'), selected=selected.get('now'), nodes=selected.get('all', []))
        print(json.dumps(result, ensure_ascii=False))
        return
    elif action == 'subscribe':
        url = validate_url(data.get('url', ''))
        name = str(data.get('name', '')).strip()[:80] or ('订阅 ' + str(len(store['items']) + 1))
        store_subscription(store, url, name, download(url))
    elif action == 'activate':
        item = find_profile(store, data.get('id'))
        subscription = yaml.safe_load((PROFILES / (item['id'] + '.yaml')).read_text())
        apply_subscription(subscription)
        store['active'] = item['id']
        save_registry(store)
    elif action == 'delete':
        item = find_profile(store, data.get('id'))
        if item['id'] == store['active']:
            raise PublicError('请先切换到其他配置，再删除当前配置。')
        store['items'].remove(item)
        save_registry(store)
        (PROFILES / (item['id'] + '.yaml')).unlink(missing_ok=True)
    elif action == 'rename':
        item = find_profile(store, data.get('id'))
        name = str(data.get('name', '')).strip()
        if not name or len(name) > 80:
            raise PublicError('请输入 1 至 80 字的配置名称。')
        item['name'] = name
        save_registry(store)
    elif action == 'mode':
        mode = data.get('mode')
        if mode not in ('rule', 'global', 'direct'):
            raise PublicError('代理模式不正确。')
        api('/configs', 'PATCH', {'mode': mode})
        config = yaml.safe_load(CONFIG.read_text())
        config['mode'] = mode
        write_private(CONFIG, yaml.safe_dump(config, allow_unicode=True, sort_keys=False), core=True)
    elif action == 'select':
        name = data.get('name')
        group = data.get('group', 'Proxy')
        if not isinstance(group, str) or name not in api('/proxies')['proxies'].get(group, {}).get('all', []):
            raise PublicError('节点不存在。')
        api('/proxies/' + urllib.parse.quote(group, safe=''), 'PUT', {'name': name})
    elif action == 'refresh':
        item = find_profile(store, data.get('id') or store['active'])
        subscription = download(item['url'])
        if item['id'] == store['active']:
            apply_subscription(subscription)
        else:
            # 非当前配置同样先校验，避免无效订阅覆盖缓存。
            candidate = ROOT / 'candidate.yaml'
            write_private(candidate, yaml.safe_dump(compose(subscription), allow_unicode=True, sort_keys=False), core=True)
            check = subprocess.run(['runuser', '-u', 'aihub-clash', '--', '/usr/bin/verge-mihomo', '-t', '-d', str(ROOT), '-f', str(candidate)], capture_output=True, timeout=50)
            candidate.unlink(missing_ok=True)
            if check.returncode:
                raise PublicError('配置校验失败，已保留旧配置。')
        write_private(PROFILES / (item['id'] + '.yaml'), yaml.safe_dump(subscription, allow_unicode=True, sort_keys=False))
        item.update(updated=int(time.time()), nodes=len(subscription['proxies']), groups=len(subscription.get('proxy-groups', [])), rules=len(subscription.get('rules', [])))
        save_registry(store)
    print('{"ok":true}')


if __name__ == '__main__':
    try:
        # 与订阅自动更新共用锁，避免多页同时切换或覆盖配置。
        with (ROOT / 'management.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            main()
    except PublicError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
    except Exception:
        print(json.dumps({'error': '操作失败，请检查服务状态、节点兼容性或网络；原订阅记录仍保留。'}, ensure_ascii=False))
        sys.exit(1)
