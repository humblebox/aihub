#!/usr/bin/env python3
"""网页服务专用提权入口，仅允许设备接入及固定的本机代理管理操作。"""
import json
import re
import subprocess
import sys

args = sys.argv[1:]
if args and args[0] == 'clash':
    if len(args) != 3 or args[1] not in ('status', 'subscribe', 'mode', 'select', 'refresh', 'start', 'stop', 'profiles', 'activate', 'delete', 'rename') or len(args[2]) > 6000:
        raise SystemExit('代理参数不正确')
    result = subprocess.run(['/usr/bin/python3', '/opt/aihub/clash/manage.py', *args[1:]], capture_output=True, text=True)
    if result.returncode:
        try:
            message = json.loads(result.stdout).get('error', '')
        except (ValueError, AttributeError):
            message = ''
        sys.stderr.write(message if isinstance(message, str) and len(message) < 300 else '代理操作失败，请检查服务状态。')
    else:
        sys.stdout.write(result.stdout)
    raise SystemExit(result.returncode)
if not args or args[0] not in ('create', 'command'):
    raise SystemExit('不允许的操作')
if len(args) < 2 or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', args[1]):
    raise SystemExit('设备标识不正确')
if args[0] == 'command' and len(args) != 2:
    raise SystemExit('参数不正确')
if args[0] == 'create':
    if len(args) not in (4, 6) or args[2] != '--name' or len(args[3]) > 80 or any(ord(c) < 32 for c in args[3]):
        raise SystemExit('设备名称不正确')
if len(args) == 6 and (args[4] != '--platform' or args[5] not in ('linux', 'windows', 'android')):
    raise SystemExit('系统类型不正确')
raise SystemExit(subprocess.run(['/usr/bin/python3', '/opt/aihub/enrollment/enroll_server.py', *args]).returncode)
