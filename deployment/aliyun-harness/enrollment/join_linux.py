#!/usr/bin/env python3
"""在目标 Linux 上配置 SSH、FRP，并使用限时凭据回传设备信息。"""
import argparse
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import sys
import time


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='将当前 Linux 电脑接入云端远程设备列表')
    parser.add_argument('--workspace', default=os.getcwd(), help='允许 AI 开始工作的项目目录')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
        parser.error('当前安装包仅支持 x86_64 Linux，请勿用于其他架构')
    base = Path(__file__).resolve().parent
    info = json.loads((base / 'info.json').read_text())
    if time.time() > info['expires']:
        parser.error('接入凭据已过期，请在管理电脑重新生成')
    user = pwd.getpwuid(os.geteuid()).pw_name
    home = Path(pwd.getpwnam(user).pw_dir)
    workspace = Path(args.workspace).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        parser.error('项目路径必须是已经存在的目录')
    prefix = [] if os.geteuid() == 0 else ['sudo']
    if prefix:
        run(prefix + ['-v'])
    if not Path('/usr/sbin/sshd').exists():
        if not shutil.which('apt-get'):
            parser.error('当前自动安装 SSH 仅支持 Ubuntu/Debian；其他系统请先安装 openssh-server')
        run(prefix + ['apt-get', 'update'])
        run(prefix + ['apt-get', 'install', '-y', 'openssh-server'])
    run(prefix + ['systemctl', 'enable', '--now', 'ssh'])
    sshdir = home / '.ssh'
    sshdir.mkdir(mode=0o700, exist_ok=True)
    auth = sshdir / 'authorized_keys'
    pub = (base / 'authorized.pub').read_text().strip()
    existing = auth.read_text() if auth.exists() else ''
    if pub not in existing:
        with auth.open('a') as f:
            f.write(('\n' if existing and not existing.endswith('\n') else '') + 'restrict,port-forwarding,pty ' + pub + '\n')
    auth.chmod(0o600)
    device = info['id']
    bindir = home / '.local/share/aihub' / device
    confdir = home / '.config/aihub' / device
    bindir.mkdir(parents=True, exist_ok=True)
    confdir.mkdir(parents=True, mode=0o700, exist_ok=True)
    confdir.chmod(0o700)
    binary = bindir / 'frpc'
    config = confdir / 'frpc.toml'
    staged_binary = bindir / 'frpc.new'
    shutil.copyfile(base / 'frpc', staged_binary)
    staged_binary.chmod(0o755)
    staged_binary.replace(binary)
    staged_config = confdir / 'frpc.toml.new'
    shutil.copyfile(base / 'frpc.toml', staged_config)
    staged_config.chmod(0o600)
    staged_config.replace(config)
    run([str(binary), 'verify', '-c', str(config)], stdout=subprocess.DEVNULL)
    service = 'aihub-frpc-' + device + '.service'
    # 系统服务以当前普通用户运行，退出桌面登录后仍保持连接。
    unit = ('[Unit]\nDescription=AIHub 远程设备 ' + device + '\n'
            'After=network-online.target\nWants=network-online.target\n'
            '[Service]\nUser=' + user + '\n'
            'ExecStart=' + json.dumps(str(binary), ensure_ascii=False) + ' -c ' + json.dumps(str(config), ensure_ascii=False) + '\n'
            'Restart=always\nRestartSec=5\nNoNewPrivileges=true\nUMask=0077\n'
            '[Install]\nWantedBy=multi-user.target\n')
    unitfile = base / service
    unitfile.write_text(unit)
    run(prefix + ['install', '-m', '644', str(unitfile), '/etc/systemd/system/' + service])
    run(prefix + ['systemctl', 'daemon-reload'])
    run(prefix + ['systemctl', 'enable', '--now', service])
    hostkey = Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().strip()
    payload = json.dumps({'user': user, 'workspace': str(workspace), 'hostkey': hostkey}).encode()
    (base / 'enroll_key').chmod(0o600)
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
               '-o', 'UserKnownHostsFile=' + str(base / 'cloud_known_hosts'),
               '-i', str(base / 'enroll_key'), 'root@' + info['server'], 'register']
    # 隧道启动可能需要数秒；只重试注册校验，不重放远程业务任务。
    last = None
    for attempt in range(12):
        last = subprocess.run(command, input=payload, capture_output=True)
        if last.returncode == 0:
            print(last.stdout.decode())
            print('接入完成：网页 → 设置 → 远程工作区 → 刷新，选择设备及项目目录。')
            print('服务：' + service + '；退出登录后仍会保持连接。')
            print('请删除本接入脚本；其中包含长期使用的 FRP 凭据。')
            return
        time.sleep(2)
    print(last.stderr.decode(), file=sys.stderr)
    raise SystemExit('注册失败。SSH/FRP 已安装，可在凭据有效期内重新执行此脚本；排查后勿重复生成其他设备。')


if __name__ == '__main__':
    main()
