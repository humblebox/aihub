#!/usr/bin/env python3
"""生成新服务器配置和专属凭据，不导入现有生产服务器数据。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import yaml


def command(*args):
    subprocess.run(list(args), check=True)


def write(path, text, mode=0o600, user=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    if user:
        account = pwd.getpwnam(user)
        os.chown(path, account.pw_uid, account.pw_gid)


def provision(source, host, country):
    for user, home in [('aihub', '/var/lib/aihub'), ('aihub-clash', '/var/lib/aihub-clash')]:
        try:
            pwd.getpwnam(user)
        except KeyError:
            command('useradd', '--system', '--create-home', '--home-dir', home, '--shell', '/usr/sbin/nologin', user)
    origin = 'https://' + host
    deployment = source / 'deployment/aliyun-harness'
    for folder in ['login', 'enrollment', 'web-enrollment', 'clash']:
        shutil.copytree(deployment / folder, '/opt/aihub/' + folder, ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
    shutil.copyfile(deployment / 'clash/panel.html', '/opt/aihub/web-enrollment/clash.html')
    write('/etc/aihub/deployment.json', json.dumps({'host': host, 'origin': origin}))
    profile = Path('/var/lib/aihub/.dsh/profiles/web')
    profile.mkdir(parents=True, exist_ok=True)
    bundles = ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app', 'dsh-remote', '@deepseek-ai/dsh-experimental-plugin-market-bundle', 'aihub-device-enrollment']
    write(profile / 'package.json', json.dumps({'name': 'dsh-profile-web', 'private': True, 'dependencies': {'dsh-remote': '0.8.71'}, 'dsh': {'profile': {'bundles': bundles}}}), user='aihub')
    write(profile / 'pnpm-workspace.yaml', 'packages:\n  - .\nnodeLinker: hoisted\nautoInstallPeers: false\n', user='aihub')
    write(profile / 'cordis.yml', '[]\n', user='aihub')
    patches = [
        {'id': 'connection', 'config': {'trustedHosts': [host], 'cookieMaxAgeDays': 30}},
        {'id': 'dsh-remote', 'config': {'backend': 'openssh', 'hostKeyMode': 'verify', 'updateMode': 'off', 'commandTimeoutMs': 60000}},
    ]
    write(profile / 'cordis.patch.yml', yaml.safe_dump(patches, allow_unicode=True, sort_keys=False), user='aihub')
    (profile / 'node_modules').mkdir(exist_ok=True)
    for name, target in [('aihub-device-enrollment', '/opt/aihub/web-enrollment')]:
        link = profile / 'node_modules' / name
        if not link.exists():
            link.symlink_to(target)
    Path('/var/lib/aihub/workspace').mkdir(parents=True, exist_ok=True)
    Path('/var/lib/aihub/.ssh').mkdir(mode=0o700, exist_ok=True)
    write('/var/lib/aihub/.ssh/config', '', user='aihub')
    Path('/root/.ssh').mkdir(mode=0o700, parents=True, exist_ok=True)
    command('chown', '-R', 'aihub:aihub', '/var/lib/aihub')
    # 插件由 profile 管理并生成真实锁文件，以支持网页更新及精确回滚。
    command('runuser', '-u', 'aihub', '--', 'env', 'HOME=/var/lib/aihub',
            'PATH=/opt/aihub/node-v24.22.2-linux-x64/bin:/usr/bin:/bin',
            '/opt/aihub/node-v24.22.2-linux-x64/bin/pnpm', '--dir', str(profile),
            'install', '--ignore-scripts')
    token = secrets.token_urlsafe(40)
    write('/etc/aihub/frps.toml', 'bindPort = 7000\nproxyBindAddr = "127.0.0.1"\nauth.method = "token"\nauth.token = ' + json.dumps(token) + '\nallowPorts = [{ start = 20000, end = 20999 }]\n', mode=0o640, user='aihub')
    password = secrets.token_urlsafe(18)
    username = os.environ.get('AIHUB_ADMIN_USER', 'admin')
    if not username or len(username) > 80 or not username.isascii():
        raise ValueError('管理员用户名需为1至80个ASCII字符')
    salt = secrets.token_bytes(16)
    account = {'username': username, 'salt': salt.hex(), 'password_hash': hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex(), 'session_key': secrets.token_hex(32)}
    Path('/var/lib/aihub-login').mkdir(mode=0o700, exist_ok=True)
    write('/var/lib/aihub-login/account.json', json.dumps(account))
    note = f'登录地址：{origin}/login\n用户名：{username}\n密码：{password}\n'
    write('/var/lib/aihub-login/初始登录信息.txt', note)
    write('/root/aihub-initial-login.txt', note)
    Path('/var/lib/aihub-clash').mkdir(mode=0o700, exist_ok=True)
    config = {'mixed-port': 7890, 'allow-lan': False, 'bind-address': '127.0.0.1', 'mode': 'rule', 'log-level': 'warning', 'external-controller': '127.0.0.1:9090', 'secret': secrets.token_urlsafe(40), 'tun': {'enable': False}, 'profile': {'store-selected': True}, 'proxies': [], 'proxy-groups': [{'name': 'Proxy', 'type': 'select', 'proxies': ['DIRECT']}], 'rules': ['MATCH,Proxy']}
    write('/var/lib/aihub-clash/config.yaml', yaml.safe_dump(config, sort_keys=False), user='aihub-clash')
    shutil.copyfile(country, '/var/lib/aihub-clash/Country.mmdb')
    command('chown', '-R', 'aihub-clash:aihub-clash', '/var/lib/aihub-clash')
    for item in [deployment / 'aihub-harness.service', deployment / 'aihub-frps.service', deployment / 'login/aihub-login.service', *list((deployment / 'clash').glob('*.service')), *list((deployment / 'clash').glob('*.timer'))]:
        shutil.copyfile(item, Path('/etc/systemd/system') / item.name)
    write('/etc/systemd/system/aihub-enrollment.service', '''[Unit]
Description=AIHub 设备接入管理
After=network.target
[Service]
ExecStart=/usr/bin/python3 /opt/aihub/enrollment/web_broker.py
RuntimeDirectory=aihub-enrollment
RuntimeDirectoryMode=0755
Restart=on-failure
UMask=0077
[Install]
WantedBy=multi-user.target
''', 0o644)
    write('/etc/systemd/system/aihub-login.service.d/origin.conf', '[Service]\nEnvironment=AIHUB_PUBLIC_ORIGIN=' + origin + '\n', 0o644)
    Path('/etc/aihub/tls').mkdir(parents=True, exist_ok=True)
    san = ('IP:' if all(c in '0123456789.' for c in host) else 'DNS:') + host
    command('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '365', '-keyout', '/etc/aihub/tls/server.key', '-out', '/etc/aihub/tls/server.crt', '-subj', '/CN=' + host, '-addext', 'subjectAltName=' + san)
    Path('/etc/aihub/tls/server.key').chmod(0o600)
    template = (source / 'scripts/nginx.conf.template').read_text().replace('AIHUB_HOST_PLACEHOLDER', host)
    write('/etc/nginx/sites-available/aihub', template, 0o644)
    enabled = Path('/etc/nginx/sites-enabled/aihub')
    enabled.parent.mkdir(parents=True, exist_ok=True)
    if not enabled.exists():
        enabled.symlink_to('/etc/nginx/sites-available/aihub')
    # 上游安装器同时生成面板控制密钥文件，Nginx模板已包含对应位置，不重复插入。
    command('/usr/bin/python3', '/opt/aihub/clash/install_dashboard.py')
    print('配置与随机凭据已生成；密码没有写入输出。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--country', type=Path, required=True)
    args = parser.parse_args()
    provision(args.source, args.host, args.country)
