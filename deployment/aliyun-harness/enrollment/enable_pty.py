#!/usr/bin/env python3
"""在云端为旧 Linux／安卓设备的专属接入密钥启用 PTY，默认仅检查。"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

REMOTE = r'''
import datetime, json, os, shutil, sys, tempfile
from pathlib import Path
request = json.load(sys.stdin)
p = Path.home() / '.ssh/authorized_keys'
if p.is_symlink():
    raise SystemExit('拒绝修改符号链接 authorized_keys')
source = p.read_text()
lines = source.splitlines(keepends=True)
matches = []
for i, line in enumerate(lines):
    fields = line.split()
    if len(fields) >= 3 and fields[1:3] == request['public'].split():
        matches.append(i)
if len(matches) != 1:
    raise SystemExit('未找到唯一的 AIHub 专属密钥，未修改')
i = matches[0]
options = lines[i].split()[0]
if options == 'restrict,port-forwarding,pty':
    print('已启用，无需修改'); sys.exit(0)
if options != 'restrict,port-forwarding':
    raise SystemExit('密钥限制不是标准接入格式，需人工检查，未修改')
if not request['apply']:
    print('待启用 PTY（仅检查）'); sys.exit(0)
backup = p.with_name('authorized_keys.before-aihub-pty-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S%f'))
shutil.copy2(p, backup)
backup.chmod(0o600)
lines[i] = lines[i].replace('restrict,port-forwarding ', 'restrict,port-forwarding,pty ', 1)
fd, name = tempfile.mkstemp(dir=p.parent, prefix='.aihub-pty-')
try:
    with os.fdopen(fd, 'w') as f:
        f.write(''.join(lines)); f.flush(); os.fsync(f.fileno())
    if p.read_text() != source:
        raise RuntimeError('公钥文件已被其他进程修改，已停止')
    os.replace(name, p)
finally:
    if os.path.exists(name): os.unlink(name)
print('已启用 PTY，原文件已备份')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--device', help='指定设备标识，例如 demo-linux')
    group.add_argument('--all', action='store_true', help='处理所有已接入的 Linux／安卓设备')
    parser.add_argument('--apply', action='store_true', help='执行修改；省略时仅检查')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('请在云服务器使用 sudo 或 root 执行')
    if args.device and not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', args.device):
        parser.error('设备标识格式不正确')
    root = Path('/var/lib/aihub')
    records = [root / 'enrollment' / (args.device + '.json')] if args.device else sorted((root / 'enrollment').glob('*.json'))
    failed = 0
    for record in records:
        label = record.stem
        try:
            data = json.loads(record.read_text())
            if data.get('status') != 'joined':
                print(label + '：跳过，尚未完成接入'); continue
            if data.get('platform', 'linux') not in ('linux', 'android'):
                print(label + '：跳过，此脚本只支持 Linux／安卓'); continue
            if data.get('id') != label or data.get('alias') != 'aihub-' + label:
                raise ValueError('设备记录与别名不一致')
            public = (root / '.ssh' / ('device_' + label + '.pub')).read_text().split()
            if len(public) < 2 or public[0] != 'ssh-ed25519':
                raise ValueError('专属公钥格式不正确')
            payload = json.dumps({'public': ' '.join(public[:2]), 'apply': args.apply})
            interpreter = 'python' if data.get('platform') == 'android' else 'python3'
            result = subprocess.run(['runuser', '-u', 'aihub', '--', 'ssh', '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8', data['alias'],
                interpreter + ' -c ' + shlex.quote(REMOTE)], input=payload, text=True,
                capture_output=True, timeout=25)
            if result.returncode:
                raise ValueError(result.stderr.strip()[-300:] or '远程脚本失败')
            print(label + '：' + result.stdout.strip())
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            failed += 1
            print(label + '：失败，' + str(error))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
