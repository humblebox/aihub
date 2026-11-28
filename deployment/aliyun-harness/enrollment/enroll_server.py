#!/usr/bin/env python3
"""云端管理工具：生成 Linux 接入脚本，校验回调并登记 SSH 主机。"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import io
import http.cookiejar
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from platform_bundle import windows_bundle, android_command

ROOT = Path('/var/lib/aihub')
STATE = ROOT / 'enrollment'
SSH = ROOT / '.ssh'
SERVER = json.loads(Path('/etc/aihub/deployment.json').read_text())['host'] if Path('/etc/aihub/deployment.json').exists() else 'localhost'
SCRIPT = Path('/opt/aihub/enrollment/enroll_server.py')


def validate_id(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', value):
        raise ValueError('设备标识只能包含小写字母、数字、下划线和短横线，长度为 1—40')
    return value


def validate_payload(value, platform="linux"):
    if not isinstance(value, dict) or set(value) != {'user', 'workspace', 'hostkey'}:
        raise ValueError('注册数据字段不正确')
    user, workspace, hostkey = (value[k] for k in ('user', 'workspace', 'hostkey'))
    if not isinstance(user, str) or not (re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', user) if platform != 'windows' else 0 < len(user) <= 64 and not re.search(r'[\x00-\x20\x7f"\\]', user)):
        raise ValueError('SSH 用户名格式不正确')
    if not isinstance(workspace, str) or not (re.match(r'^[A-Za-z]:/', workspace) if platform == 'windows' else workspace.startswith('/')) or len(workspace) > 4096 or any(ord(c) < 32 for c in workspace):
        raise ValueError('项目目录必须为绝对路径，且不能包含控制字符')
    if not isinstance(hostkey, str):
        raise ValueError('SSH 主机公钥格式不正确')
    parts = hostkey.split()
    if len(parts) < 2 or parts[0] != 'ssh-ed25519':
        raise ValueError('仅接受 Ed25519 主机公钥')
    raw = base64.b64decode(parts[1], validate=True)
    if len(raw) != 51 or raw[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise ValueError('Ed25519 主机公钥内容不正确')
    return user, workspace, ' '.join(parts[:2])


def atomic(path, text, owner=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, 0o600)
        if owner:
            os.chown(name, owner.pw_uid, owner.pw_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / '.lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def save(record):
    atomic(STATE / (record['id'] + '.json'), json.dumps(record, ensure_ascii=False, indent=2) + '\n')


def root_auth_change(pub, add=None):
    path = Path('/root/.ssh/authorized_keys')
    old = path.read_text() if path.exists() else ''
    rows = [row for row in old.splitlines() if pub.split()[1] not in row]
    if add:
        rows.append(add)
    atomic(path, '\n'.join(rows) + '\n')


def frp_token():
    text = Path('/etc/aihub/frps.toml').read_text()
    match = re.search(r'^\s*auth\.token\s*=\s*("(?:[^"\\]|\\.)*")\s*$', text, re.M)
    if not match:
        raise ValueError('未找到当前 FRP 令牌配置')
    return json.loads(match[1])


def create(args):
    device = validate_id(args.id)
    if not 1 <= args.minutes <= 1440:
        raise ValueError('接入有效期必须为 1—1440 分钟')
    with locked():
        if (STATE / (device + '.json')).exists():
            raise ValueError('设备标识已存在，请使用另一个标识')
        alias = 'aihub-' + device
        cfg = (SSH / 'config').read_text()
        if re.search(r'^Host\s+' + re.escape(alias) + r'\s*$', cfg, re.M):
            raise ValueError('SSH 别名已存在')
        records = [json.loads(p.read_text()) for p in STATE.glob('*.json')]
        used = {r['port'] for r in records}
        used.update(int(p) for p in re.findall(r'^\s*Port\s+(\d+)', cfg, re.M))
        listeners = subprocess.check_output(['ss', '-lntH'], text=True)
        used.update(int(p) for p in re.findall(r':(20\d{3})\s', listeners))
        port = next((p for p in range(20002, 21000) if p not in used), None)
        if port is None:
            raise ValueError('没有可用的 FRP 映射端口')
        key = SSH / ('device_' + device)
        if key.exists():
            raise ValueError('设备密钥文件已存在')
        owner = pwd.getpwnam('aihub')
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key), '-C', alias], check=True)
        for p in (key, Path(str(key) + '.pub')):
            os.chown(p, owner.pw_uid, owner.pw_gid)
        record = {'platform': args.platform, 'id': device, 'name': args.name or device, 'port': port, 'alias': alias,
                  'expires': int(time.time()) + args.minutes * 60, 'status': 'pending'}
        outdir = Path('/root/aihub-enrollment')
        outdir.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            b = Path(temp)
            ekey = b / 'enroll_key'
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(ekey), '-C', 'aihub-enroll-' + device], check=True)
            pub = Path(str(ekey) + '.pub').read_text().strip()
            record['callback_pub'] = pub
            shutil.copyfile(key.with_suffix('.pub'), b / 'authorized.pub')
            shutil.copyfile(SCRIPT.parent / 'join_linux.py', b / 'join_linux.py')
            shutil.copyfile('/opt/aihub/frp/frpc', b / 'frpc')
            if args.platform == 'android':
                shutil.copyfile(SCRIPT.parent / 'join_android.py', b / 'join_linux.py')
                # 安卓从 Termux 仓库安装 frpc，包中不放不兼容的 Linux 二进制。
                (b / 'frpc').write_bytes(b'')
            if args.platform == 'windows':
                shutil.copyfile(SCRIPT.parent / 'join_windows.ps1', b / 'join_windows.ps1')
                shutil.copyfile('/opt/aihub/downloads/frpc-windows.exe', b / 'frpc.exe')
            (b / 'frpc.toml').write_text(
                'serverAddr = ' + json.dumps(SERVER) + '\nserverPort = 7000\n'
                'auth.method = "token"\nauth.token = ' + json.dumps(frp_token()) + '\n'
                'transport.tls.enable = true\n[[proxies]]\nname = ' + json.dumps('device-' + device) + '\n'
                'type = "tcp"\nlocalIP = "127.0.0.1"\nlocalPort = ' + ('8022' if args.platform == 'android' else '22') + '\nremotePort = ' + str(port) + '\n')
            hostkey = Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()
            (b / 'cloud_known_hosts').write_text(SERVER + ' ' + ' '.join(hostkey[:2]) + '\n')
            (b / 'info.json').write_text(json.dumps({**record, 'server': SERVER}))
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode='w:gz') as tar:
                for name in ('enroll_key', 'authorized.pub', 'join_linux.py', 'frpc', 'frpc.toml', 'cloud_known_hosts', 'info.json'):
                    tar.add(b / name, arcname=name)
            encoded = base64.encodebytes(payload.getvalue()).decode()
            # 安装脚本只解包本工具生成的固定文件，不从公网执行任意下载内容。
            header = '''#!/bin/bash
# AIHub Linux 私有接入脚本，请勿公开或转发。
set -euo pipefail
command -v python3 >/dev/null || { echo '请先安装 python3'; exit 1; }
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
sed '1,/^__AIHUB_PAYLOAD__$/d' "$0" | base64 -d | tar -xz -C "$task_tmp"
python3 "$task_tmp/join_linux.py" "$@"
exit
__AIHUB_PAYLOAD__
'''
            output = outdir / ('aihub-join-' + device + '.sh')
            atomic(output, header + encoded)
            command = '/usr/bin/python3 ' + str(SCRIPT) + ' dispatch ' + device
            root_auth_change(pub, 'restrict,command=' + json.dumps(command) + ' ' + pub)
            record['script'] = str(output)
            # 限时下载凭据只能读取此设备安装包或提交注册，不能执行任意云端命令。
            bootstrap = (
                "import base64,os,pathlib,shutil,subprocess,tempfile; "
                "shutil.which('ssh') or subprocess.run(['sudo','apt-get','install','-y','openssh-client'],check=True); "
                "task_dir=tempfile.TemporaryDirectory(prefix='aihub-join-'); "
                "task_root=pathlib.Path(task_dir.name); "
                "task_key=task_root/'key'; "
                "task_key.write_bytes(base64.b64decode(" + repr(base64.b64encode(ekey.read_bytes()).decode()) + ")); "
                "task_key.chmod(0o600); "
                "task_hosts=task_root/'known_hosts'; "
                "task_hosts.write_text(" + repr(SERVER + ' ' + ' '.join(hostkey[:2]) + '\n') + "); "
                "task_script=task_root/'join.sh'; "
                "task_ssh=['ssh','-o','BatchMode=yes','-o','IdentitiesOnly=yes',"
                "'-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',"
                "'-o','ServerAliveInterval=10','-o','ServerAliveCountMax=3',"
                "'-o','UserKnownHostsFile='+str(task_hosts),'-i',str(task_key),'root@" + SERVER + "','download']; "
                "task_data=subprocess.check_output(task_ssh,timeout=120); task_script.write_bytes(task_data); "
                "task_result=subprocess.run(['bash',str(task_script),'--workspace',os.getcwd()]); "
                "task_dir.cleanup(); raise SystemExit(task_result.returncode)"
            )
            terminal_command = 'python3 -c ' + shlex.quote(bootstrap) + '\n'
            if args.platform == 'android':
                terminal_command = android_command(bootstrap)
            elif args.platform == 'windows':
                package, terminal_command = windows_bundle(b, {**record, 'server': SERVER}, SERVER + ' ' + ' '.join(hostkey[:2]))
                atomic(output, package)
            # 网页下载服务不能读取 /root；启动脚本仍仅允许 root 读取。
            commanddir = STATE / 'bootstrap'
            commanddir.mkdir(mode=0o700, exist_ok=True)
            commandfile = commanddir / ('aihub-join-' + device + '.command.txt')
            atomic(commandfile, '# 在目标设备的项目目录内执行，自动使用当前目录。\n'
                   + terminal_command)
            record['command'] = str(commandfile)
            # 固定服务器公钥，支持自签名 HTTPS，同时防止下载脚本被替换。
            public_key = subprocess.check_output(['openssl', 'x509', '-in', '/etc/aihub/tls/server.crt', '-pubkey', '-noout'])
            der = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=public_key, capture_output=True, check=True).stdout
            pin = 'sha256//' + base64.b64encode(hashlib.sha256(der).digest()).decode()
            record['join_token'] = secrets.token_urlsafe(24)
            url = 'https://' + SERVER + '/join/' + device + '/' + record['join_token']
            fetch = 'curl -fsSk --pinnedpubkey ' + shlex.quote(pin) + ' ' + shlex.quote(url)
            record['short_command'] = '(set -o pipefail; ' + fetch + ' | bash)\n'
            if args.platform == 'windows':
                record['short_command'] = '$j=' + fetch.replace('curl ', 'curl.exe ', 1) + ';if($LASTEXITCODE -ne 0){throw "下载失败"};& ([scriptblock]::Create(($j -join "`n")))\n'
            save(record)
        print(json.dumps({'id': device, 'name': record['name'], 'port': port,
                          'expires': record['expires'], 'script': str(output), 'command': str(commandfile)}, ensure_ascii=False))


def register_plugin(record, user, workspace):
    """通过现成插件的本机认证接口登记设备，不修改其内存中的注册表。"""
    url = subprocess.check_output(['/usr/bin/python3', '/opt/aihub/login/harness_auth.py'], text=True).strip()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        with opener.open(url, timeout=10) as response:
            response.read()
        data = {'action': 'add', 'id': 'enrolled-' + record['id'], 'name': record['name'],
                'host': record['alias'], 'useSshConfig': True, 'username': user,
                'backend': 'openssh', 'workspace': workspace, 'hostKeyMode': 'verify'}
        request = urllib.request.Request('http://127.0.0.1:3080/api/dsh-remote/machines',
                  data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=15) as response:
            result = json.load(response)
        if not result.get('ok'):
            raise ValueError('远程插件拒绝设备登记')
    except (OSError, ValueError):
        raise ValueError('无法通过网页接口登记设备，请确认 aihub-harness 正常后重试') from None


def finish(device):
    validate_id(device)
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise ValueError('注册数据过大')
    preliminary = json.loads((STATE / (device + '.json')).read_text())
    user, workspace, hostkey = validate_payload(json.loads(raw), preliminary.get('platform', 'linux'))
    with locked():
        record = json.loads((STATE / (device + '.json')).read_text())
        if record['status'] != 'pending' or time.time() > record['expires']:
            raise ValueError('接入凭据已使用、取消或过期')
        port, alias = record['port'], record['alias']
        key = SSH / ('device_' + device)
        owner = pwd.getpwnam('aihub')
        knownline = '[127.0.0.1]:' + str(port) + ' ' + hostkey + '\n'
        # 先使用回传公钥严格校验隧道中的 SSH 服务，再写入正式主机配置。
        probe = SSH / ('.enroll-known-' + device)
        atomic(probe, knownline, owner)
        try:
            probe_command = 'test -d ' + shlex.quote(workspace) + ' && hostname'
            if record.get('platform') == 'windows':
                script = "if (!(Test-Path -LiteralPath '" + workspace.replace("'", "''") + "' -PathType Container)) { exit 2 }; hostname"
                probe_command = 'powershell.exe -NoProfile -EncodedCommand ' + base64.b64encode(script.encode('utf-16le')).decode()
            check = subprocess.run(['runuser', '-u', 'aihub', '--', 'ssh', '-F', '/dev/null',
                '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=6',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlgorithms=ssh-ed25519',
                '-o', 'UserKnownHostsFile=' + str(probe), '-i', str(key), '-p', str(port),
                user + '@127.0.0.1', probe_command],
                capture_output=True, text=True, timeout=12)
            if check.returncode:
                raise ValueError('SSH 校验未通过，请确认隧道已连接、用户名及项目目录正确：' + check.stderr.strip()[:300])
        finally:
            probe.unlink(missing_ok=True)
        cfg = SSH / 'config'
        old = cfg.read_text()
        addition = ('\n# AIHub 自动接入设备：' + device + '\nHost ' + alias + '\n'
                    ' HostName 127.0.0.1\n Port ' + str(port) + '\n User ' + user + '\n'
                    ' IdentityFile ' + str(key) + '\n IdentitiesOnly yes\n StrictHostKeyChecking yes\n')
        if re.search(r'^Host\s+' + re.escape(alias) + r'\s*$', old, re.M) and addition.strip() not in old:
            raise ValueError('SSH 别名已经存在，停止以防覆盖')
        # 新版分离 OpenSSH 文本与原生后端 JSON，避免把公钥行写进 JSON 注册表。
        plugin_manifest = ROOT / '.dsh/profiles/web/node_modules/dsh-remote/package.json'
        plugin_version = json.loads(plugin_manifest.read_text())['version']
        plugin_known_name = 'known_hosts.json' if plugin_version.startswith('0.') else 'known_hosts'
        for known in (SSH / 'known_hosts', ROOT / '.dsh/remote-workspaces' / plugin_known_name):
            text = known.read_text() if known.exists() else ''
            if knownline.strip() not in text.splitlines():
                atomic(known, text.rstrip('\n') + '\n' + knownline, owner)
        if addition.strip() not in old:
            atomic(cfg, old.rstrip('\n') + '\n' + addition, owner)
        register_plugin(record, user, workspace)
        record.update(status='joined', user=user, workspace=workspace, hostname=check.stdout.strip(), joined=int(time.time()))
        save(record)
        root_auth_change(record['callback_pub'])
        Path(record['script']).unlink(missing_ok=True)
        if record.get('command'):
            Path(record['command']).unlink(missing_ok=True)
        print('设备接入成功：' + record['name'] + '（' + alias + '）')
        print('远程主机：' + record['hostname'] + '；项目目录：' + workspace)


def main():
    parser = argparse.ArgumentParser(description='生成并管理 Linux 一键接入凭据')
    sub = parser.add_subparsers(dest='op', required=True)
    add = sub.add_parser('create', help='生成私有接入脚本')
    add.add_argument('id')
    add.add_argument('--name')
    add.add_argument('--platform', choices=['linux', 'windows', 'android'], default='linux')
    add.add_argument('--minutes', type=int, default=60)
    sub.add_parser('list', help='列出接入状态')
    for op in ('finish', 'cancel', 'dispatch', 'command'):
        cmd = sub.add_parser(op)
        cmd.add_argument('id')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('请以 root 运行云端管理工具')
    if args.op == 'create':
        create(args)
    elif args.op == 'finish':
        finish(args.id)
    elif args.op == 'command':
        with locked():
            record = json.loads((STATE / (validate_id(args.id) + '.json')).read_text())
            if record['status'] != 'pending' or time.time() > record['expires']:
                raise ValueError('接入命令已使用、取消或过期')
            print(record.get('short_command') or Path(record['command']).read_text(), end='')
    elif args.op == 'dispatch':
        if os.environ.get('SSH_ORIGINAL_COMMAND') == 'register':
            finish(args.id)
        elif os.environ.get('SSH_ORIGINAL_COMMAND') == 'download':
            with locked():
                record = json.loads((STATE / (validate_id(args.id) + '.json')).read_text())
                if record['status'] != 'pending' or time.time() > record['expires']:
                    raise ValueError('接入命令已使用、取消或过期')
                with Path(record['script']).open('rb') as source:
                    shutil.copyfileobj(source, sys.stdout.buffer)
        else:
            raise ValueError('此凭据只允许下载本设备安装包或完成注册')
    elif args.op == 'list':
        with locked():
            for p in sorted(STATE.glob('*.json')):
                r = json.loads(p.read_text())
                status = '已接入' if r['status'] == 'joined' else '已取消' if r['status'] == 'cancelled' else '已过期' if time.time() > r['expires'] else '等待接入'
                print(r['id'], r['name'], status, '端口=' + str(r['port']))
    else:
        with locked():
            path = STATE / (validate_id(args.id) + '.json')
            r = json.loads(path.read_text())
            if r['status'] == 'joined':
                raise ValueError('此命令只能取消尚未接入的凭据，不负责移除已接入设备')
            root_auth_change(r['callback_pub'])
            Path(r['script']).unlink(missing_ok=True)
            if r.get('command'):
                Path(r['command']).unlink(missing_ok=True)
            r['status'] = 'cancelled'
            save(r)
            print('已取消接入凭据；已复制的脚本仍含 FRP 共享令牌，请私下删除。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print('接入失败：' + str(exc), file=sys.stderr)
        sys.exit(1)
