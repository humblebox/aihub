#!/usr/bin/env python3
"""本机验证服务和统一登录；不输出密码、令牌或会话。"""
import argparse
import http.client
import json
from pathlib import Path
import re
import ssl
import subprocess
import time
import urllib.parse

parser = argparse.ArgumentParser()
parser.add_argument('--host', required=True)
args = parser.parse_args()
for service in ['aihub-harness', 'aihub-login', 'aihub-enrollment', 'aihub-frps', 'aihub-clash']:
    subprocess.run(['systemctl', 'is-active', '--quiet', service], check=True)


def request(path, body=None, cookie=''):
    connection = http.client.HTTPSConnection('127.0.0.1', 443, context=ssl._create_unverified_context(), timeout=20)
    headers = {'Host': args.host, 'Origin': 'https://' + args.host, 'Cookie': cookie}
    if body is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    connection.request('POST' if body is not None else 'GET', path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, response.getheaders(), response.read()
    connection.close()
    return result

for attempt in range(60):
    try:
        status, headers, page = request('/login')
        if status == 200:
            break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit('登录页未就绪')
csrf = re.search(rb'name="csrf" value="([^"]+)"', page)[1].decode()
cookie = next(value.split(';')[0] for key, value in headers if key.lower() == 'set-cookie')
note = Path('/root/aihub-initial-login.txt').read_text()
username = re.search(r'用户名：(.+)', note)[1]
password = re.search(r'密码：(.+)', note)[1]
for attempt in range(60):
    status, headers, page = request('/login', urllib.parse.urlencode({'username': username, 'password': password, 'csrf': csrf}), cookie)
    if status == 303:
        break
    if status != 503:
        raise SystemExit('登录验证失败：HTTP ' + str(status))
    time.sleep(1)
else:
    raise SystemExit('Harness 原生认证未就绪')
cookies = '; '.join(value.split(';')[0] for key, value in headers if key.lower() == 'set-cookie')
for path in ['/', '/devices', '/clash', '/clash/dashboard/']:
    assert request(path, cookie=cookies)[0] == 200, '登录后页面未通过：' + path
assert request('/')[0] == 302, '匿名访问未拦截'
print('服务、统一登录、AI/设备/代理页面及匿名访问保护验证通过。')
