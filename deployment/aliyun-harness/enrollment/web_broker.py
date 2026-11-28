#!/usr/bin/env python3
"""通过仅 aihub 组可访问的本机套接字提供受限设备接入操作。"""
import grp
import json
import os
import socketserver
import subprocess
from pathlib import Path

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        try:
            raw = self.rfile.readline(8193)
            if len(raw) > 8192:
                raise ValueError('请求过大')
            args = json.loads(raw)
            if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
                raise ValueError('参数不正确')
            result = subprocess.run(['/usr/bin/python3', '/opt/aihub/enrollment/web_admin.py', *args], capture_output=True, text=True, timeout=150)
            answer = {'ok': result.returncode == 0, 'output': result.stdout if result.returncode == 0 else result.stderr[:1000]}
        except Exception:
            answer = {'ok': False, 'output': '设备接入请求失败'}
        self.wfile.write((json.dumps(answer) + '\n').encode())

path = Path('/run/aihub-enrollment/control.sock')
path.unlink(missing_ok=True)
with socketserver.UnixStreamServer(str(path), Handler) as server:
    os.chown(path, 0, grp.getgrnam('aihub').gr_gid)
    path.chmod(0o660)
    server.serve_forever()
