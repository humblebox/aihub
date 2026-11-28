#!/usr/bin/env python3
"""固定网页登录入口：密码校验、持久会话及 Harness 原生登录交换。"""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import re
import secrets
import subprocess
import time
import threading
import urllib.parse

import os

PUBLIC_ORIGIN = os.environ.get("AIHUB_PUBLIC_ORIGIN", "https://localhost").rstrip("/")
PUBLIC_HOST = urllib.parse.urlsplit(PUBLIC_ORIGIN).netloc
ROOT = Path('/var/lib/aihub-login')
PAGE = Path('/opt/aihub/login/login.html').read_bytes()
ACCOUNT = json.loads((ROOT / 'account.json').read_text())
KEY = bytes.fromhex(ACCOUNT['session_key'])
ATTEMPTS = {}
ACCOUNT_LOCK = threading.RLock()
PASSWORD_PAGE = Path("/opt/aihub/login/password.html").read_bytes()


def sign(value):
    return hmac.new(KEY, value.encode(), hashlib.sha256).hexdigest()


def valid(cookie):
    try:
        value = next(x.strip().split('=', 1)[1] for x in cookie.split(';') if x.strip().startswith('aihub-login='))
        expiry, nonce, signature = value.split('.')
        body = expiry + '.' + nonce
        return int(expiry) > time.time() and hmac.compare_digest(signature, sign(body))
    except (StopIteration, ValueError):
        return False


def harness_cookie():
    # 通过原生启动令牌交换 Cookie，不修改 Harness 或关闭其认证。
    url = subprocess.check_output(['/usr/bin/python3', '/opt/aihub/login/harness_auth.py'], text=True).strip()
    connection = http.client.HTTPConnection('127.0.0.1', 3080, timeout=10)
    connection.request('GET', urllib.parse.urlsplit(url).path + '?' + urllib.parse.urlsplit(url).query, headers={'Host': PUBLIC_HOST})
    response = connection.getresponse()
    cookie = response.getheader('Set-Cookie')
    response.read();connection.close()
    if response.status != 303 or not cookie:
        raise RuntimeError('认证交换失败')
    return cookie.split(';', 1)[0]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body=b'', headers=None):
        self.send_response(code)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers();self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith('/join/'):
            # 限时能力链接只读取指定设备启动脚本，不授予网页登录或其他文件权限。
            match = re.fullmatch(r'/join/([a-z0-9][a-z0-9_-]{0,39})/([A-Za-z0-9_-]{32})', path)
            if not match:
                self.send(404);return
            try:
                record = json.loads((Path('/var/lib/aihub/enrollment') / (match[1] + '.json')).read_text())
                if not hmac.compare_digest(record.get('join_token', ''), match[2]) or record['status'] != 'pending' or time.time() >= record['expires']:
                    self.send(404);return
                command = Path(record['command'])
                expected = Path('/var/lib/aihub/enrollment/bootstrap') / ('aihub-join-' + match[1] + '.command.txt')
                if command != expected:
                    self.send(404);return
                payload = command.read_bytes()
            except (OSError, ValueError, KeyError):
                self.send(404);return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers();self.wfile.write(payload)
        elif path == '/check':
            self.send(204 if valid(self.headers.get('Cookie', '')) else 401)
        elif path in ('/login', '/account/password'):
            if path == '/account/password' and not valid(self.headers.get('Cookie', '')):
                self.send(303, headers={'Location': '/login'});return
            self.form(path)
        else:
            self.send(404)

    def form(self, path, message='', code=200):
        # 复用有效令牌，避免多个标签页或返回旧页面时互相覆盖。
        cookie = self.headers.get('Cookie', '')
        csrf = next((part.strip().split('=', 1)[1] for part in cookie.split(';') if part.strip().startswith('aihub-csrf=')), '')
        try:
            expiry, nonce, signature = csrf.split('.')
            usable = int(expiry) > time.time() + 60 and hmac.compare_digest(signature, sign('csrf:' + expiry + '.' + nonce))
        except ValueError:
            usable = False
        if not usable:
            nonce = str(int(time.time()) + 3600) + '.' + secrets.token_hex(24)
            csrf = nonce + '.' + sign('csrf:' + nonce)
        page = PASSWORD_PAGE if path == '/account/password' else PAGE
        page = page.replace(b'<!-- MESSAGE -->', message.encode()).replace(b'<!-- CSRF -->', ('<input type="hidden" name="csrf" value="' + csrf + '">').encode())
        self.send(code, page, {'Set-Cookie': 'aihub-csrf=' + csrf + '; Path=/; Max-Age=3600; Secure; HttpOnly; SameSite=Lax'})

    def do_POST(self):
        # 自签名证书下部分浏览器提交 Origin:null，使用签名双提交令牌防伪。
        origin = self.headers.get('Origin')
        if origin not in (None, 'null', PUBLIC_ORIGIN):
            self.send(403, '请求来源不正确，请重新打开登录页。'.encode());return
        if self.path == '/logout':
            self.send(303, headers={'Location': '/login', 'Set-Cookie': 'aihub-login=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax'});return
        if self.path not in ('/login', '/account/password'):
            self.send(404);return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 1 or size > 4096:
                self.send(400);return
            address = self.headers.get('X-Real-IP', '')
            now = time.time()
            history = [t for t in ATTEMPTS.get(address, []) if now - t < 600]
            ATTEMPTS[address] = history
            if len(history) >= 10:
                self.send(429, '尝试过多，请 10 分钟后重试。'.encode());return
            fields = urllib.parse.parse_qs(self.rfile.read(size).decode())
            csrf = fields.get('csrf', [''])[0]
            cookie_csrf = next((part.strip().split('=', 1)[1] for part in self.headers.get('Cookie', '').split(';') if part.strip().startswith('aihub-csrf=')), '')
            try:
                expiry, nonce, signature = csrf.split('.')
                csrf_valid = int(expiry) > now and hmac.compare_digest(signature, sign('csrf:' + expiry + '.' + nonce)) and hmac.compare_digest(csrf, cookie_csrf)
            except ValueError:
                csrf_valid = False
            if not csrf_valid:
                self.form(self.path, '登录页面已更新，请重新输入并提交；若反复出现，请允许此网站使用 Cookie。', 400);return
            if self.path == '/account/password':
                if not valid(self.headers.get('Cookie', '')):
                    self.send(303, headers={'Location': '/login'});return
                old = fields.get('old', [''])[0]
                new = fields.get('new', [''])[0]
                confirm = fields.get('confirm', [''])[0]
                digest = hashlib.scrypt(old.encode(), salt=bytes.fromhex(ACCOUNT['salt']), n=16384, r=8, p=1).hex()
                if not hmac.compare_digest(digest, ACCOUNT['password_hash']):
                    history.append(now);self.send(400, '旧密码不正确，请返回重试。'.encode());return
                if not new or new != confirm:
                    self.send(400, '新密码不能为空，且两次输入需一致。请返回重试。'.encode());return
                global KEY
                with ACCOUNT_LOCK:
                    salt = secrets.token_bytes(16)
                    updated = {**ACCOUNT, 'salt': salt.hex(), 'password_hash': hashlib.scrypt(new.encode(), salt=salt, n=16384, r=8, p=1).hex(), 'session_key': secrets.token_hex(32)}
                    temporary = ROOT / 'account.json.tmp'
                    temporary.write_text(json.dumps(updated));temporary.chmod(0o600);temporary.replace(ROOT / 'account.json')
                    ACCOUNT.update(updated);KEY = bytes.fromhex(updated['session_key'])
                    initial = ROOT / '初始登录信息.txt'
                    if initial.exists():
                        initial.write_text('密码已由管理员修改，初始密码已失效。新密码不保存明文。\n')
                self.send(200, '密码修改成功，所有设备的登录已失效。<a href="/login">重新登录</a>'.encode(), {'Set-Cookie': 'aihub-login=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax'})
                return
            username = fields.get('username', [''])[0]
            password = fields.get('password', [''])[0]
            digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(ACCOUNT['salt']), n=16384, r=8, p=1).hex()
            if not (hmac.compare_digest(username, ACCOUNT['username']) and hmac.compare_digest(digest, ACCOUNT['password_hash'])):
                history.append(now)
                self.send(401, PAGE.replace(b'<!-- MESSAGE -->', '账号或密码不正确。'.encode()).replace(b'<!-- CSRF -->', ('<input type="hidden" name="csrf" value="' + csrf + '">').encode()));return
            cookie = harness_cookie()
            body = str(int(now + 30 * 86400)) + '.' + secrets.token_hex(24)
            session = body + '.' + sign(body)
            self.send_response(303)
            self.send_header('Location', '/')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Set-Cookie', 'aihub-login=' + session + '; Path=/; Max-Age=2592000; Secure; HttpOnly; SameSite=Lax')
            self.send_header('Set-Cookie', cookie + '; Path=/; Max-Age=2592000; Secure; HttpOnly; SameSite=Lax')
            self.end_headers()
            ATTEMPTS.pop(address, None)
        except Exception:
            self.send(503, 'AI 服务暂未就绪，请稍后重新登录。'.encode())


ThreadingHTTPServer(('127.0.0.1', 3081), Handler).serve_forever()
