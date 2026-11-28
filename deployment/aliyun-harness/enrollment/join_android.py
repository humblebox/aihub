#!/usr/bin/env python3
"""在安卓 Termux 中安装 SSH／FRP，并登记当前项目目录。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='将安卓 Termux 接入 AIHub')
    parser.add_argument('--workspace', default=os.getcwd())
    args = parser.parse_args()
    prefix = Path(os.environ.get('PREFIX', ''))
    if 'com.termux' not in str(prefix) or not shutil.which('pkg'):
        parser.error('请在官方 Termux 终端运行，不是在普通安卓浏览器中运行')
    base = Path(__file__).resolve().parent
    info = json.loads((base / 'info.json').read_text())
    if time.time() > info['expires']:
        parser.error('接入命令已过期，请重新生成')
    workspace = Path(args.workspace).resolve(strict=True)
    if not workspace.is_dir():
        parser.error('当前项目目录不存在')
    run(['pkg', 'install', '-y', 'openssh', 'frp', 'termux-services'])
    home = Path.home()
    sshdir = home / '.ssh'
    sshdir.mkdir(mode=0o700, exist_ok=True)
    auth = sshdir / 'authorized_keys'
    pub = (base / 'authorized.pub').read_text().strip()
    text = auth.read_text() if auth.exists() else ''
    if pub not in text:
        with auth.open('a') as f:
            f.write('\nrestrict,port-forwarding,pty ' + pub + '\n')
    auth.chmod(0o600)
    run(['ssh-keygen', '-A'])
    configdir = home / '.config/aihub' / info['id']
    configdir.mkdir(parents=True, mode=0o700, exist_ok=True)
    config = configdir / 'frpc.toml'
    shutil.copyfile(base / 'frpc.toml', config)
    config.chmod(0o600)
    run(['frpc', 'verify', '-c', str(config)])
    # runit 管理后台进程；安卓仍可受省电机制影响，不能承诺永久在线。
    services = prefix / 'var/service'
    service = services / ('aihub-frpc-' + info['id'])
    service.mkdir(parents=True, exist_ok=True)
    import shlex
    (service / 'run').write_text('#!' + str(prefix / 'bin/sh') + '\n# AIHub 安卓远程连接\nexec frpc -c ' + shlex.quote(str(config)) + ' 2>&1\n')
    (service / 'run').chmod(0o700)
    daemon = prefix / 'etc/profile.d/start-services.sh'
    if daemon.exists():
        run(['bash', '-c', '. "$1"', 'aihub', str(daemon)])
    # 服务目录随 Termux 会话启动；先显式启动监督器以便首次立即连接。
    if not subprocess.run(['pgrep', '-f', '^runsvdir '], stdout=subprocess.DEVNULL).returncode == 0:
        subprocess.Popen(['runsvdir', str(services)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(1)
    run(['sv-enable', 'sshd'])
    run(['sv-enable', service.name])
    if shutil.which('termux-wake-lock'):
        subprocess.run(['termux-wake-lock'], check=False)
    payload = json.dumps({'user': subprocess.check_output(['whoami'], text=True).strip(),
                          'workspace': str(workspace),
                          'hostkey': (prefix / 'etc/ssh/ssh_host_ed25519_key.pub').read_text().strip()}).encode()
    (base / 'enroll_key').chmod(0o600)
    cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=8',
           '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(base / 'cloud_known_hosts'),
           '-i', str(base / 'enroll_key'), 'root@' + info['server'], 'register']
    for attempt in range(15):
        result = subprocess.run(cmd, input=payload, capture_output=True)
        if result.returncode == 0:
            print(result.stdout.decode())
            print('安卓已接入。请允许 Termux 后台运行并关闭电池优化；重启后打开 Termux 恢复服务。')
            print('如需访问共享存储，请自行执行 termux-setup-storage 并授权。')
            return
        time.sleep(2)
    raise SystemExit('注册失败：' + result.stderr.decode())


if __name__ == '__main__':
    main()
