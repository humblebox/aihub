#!/usr/bin/env python3
"""保存当前服务实例的认证入口，避免启动日志轮转导致登录和设备登记失败。"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.parse

CACHE = Path('/run/aihub-harness-auth.json')


def invocation():
    value = subprocess.check_output(['systemctl', 'show', 'aihub-harness', '--property=InvocationID', '--value'], text=True).strip()
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise RuntimeError('Harness 服务未启动')
    return value


def valid_url(value):
    if not isinstance(value, str):
        return False
    url = urllib.parse.urlsplit(value)
    return (url.scheme == 'http' and url.netloc == '127.0.0.1:3080' and url.path == '/'
            and bool(urllib.parse.parse_qs(url.query).get('token')) and not url.fragment)


def resolve():
    current = invocation()
    try:
        cached = json.loads(CACHE.read_text())
        if cached.get('invocation') == current and valid_url(cached.get('url')):
            return cached['url']
    except (OSError, ValueError):
        pass
    # 先按当前实例和启动消息过滤，再取一条，避免大量运行日志挤掉入口。
    result = subprocess.run(['journalctl', '-u', 'aihub-harness', '_SYSTEMD_INVOCATION_ID=' + current,
        '--grep=dsh web:', '-n', '1', '--no-pager', '-o', 'cat'], capture_output=True, text=True, check=False)
    urls = re.findall(r'dsh web:\s*(http://127\.0\.0\.1:3080/\S*)', result.stdout)
    if not urls or not valid_url(urls[-1]) or invocation() != current:
        raise RuntimeError('当前 Harness 认证入口尚未就绪或启动日志已轮转')
    temporary = CACHE.with_name(CACHE.name + '.' + str(os.getpid()) + '.tmp')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump({'invocation': current, 'url': urls[-1]}, output)
        temporary.replace(CACHE)
    finally:
        temporary.unlink(missing_ok=True)
    return urls[-1]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    if args.capture:
        for attempt in range(60):
            try:
                resolve()
                break
            except (RuntimeError, subprocess.SubprocessError):
                time.sleep(1)
        else:
            raise SystemExit('Harness 认证入口保存失败')
    else:
        # 仅供本机管理进程通过管道读取，不写日志。
        print(resolve())
