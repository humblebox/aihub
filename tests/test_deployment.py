"""验证可分发配置、用户输入和登录密码流程，不连接生产服务器。"""
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        directory = Path(self.temp.name)
        salt = secrets.token_bytes(16)
        self.password = 'old-password'
        account = {'username': 'admin', 'salt': salt.hex(), 'password_hash': hashlib.scrypt(self.password.encode(), salt=salt, n=16384, r=8, p=1).hex(), 'session_key': secrets.token_hex(32)}
        (directory / 'account.json').write_text(json.dumps(account))
        source = (ROOT / 'deployment/aliyun-harness/login/server.py').read_text()
        source = source.replace("Path('/var/lib/aihub-login')", 'Path(' + repr(str(directory)) + ')')
        source = source.replace("Path('/var/lib/aihub/enrollment')", 'Path(' + repr(str(directory / 'enrollment')) + ')')
        source = source.replace("Path('/var/lib/aihub/enrollment/bootstrap')", 'Path(' + repr(str(directory / 'enrollment/bootstrap')) + ')')
        source = source.replace("Path('/opt/aihub/login/login.html').read_bytes()", "b'<!-- CSRF -->'")
        source = source.replace('Path("/opt/aihub/login/password.html").read_bytes()', "b'<!-- CSRF -->'")
        source = source.replace("ThreadingHTTPServer(('127.0.0.1', 3081), Handler).serve_forever()", '')
        self.namespace = {}
        exec(compile(source, 'login-test', 'exec'), self.namespace)
        self.server = self.namespace['ThreadingHTTPServer'](('127.0.0.1', 0), self.namespace['Handler'])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        expiry = str(int(time.time() + 1000))
        body = expiry + '.session'
        self.session = body + '.' + self.namespace['sign'](body)
        csrf_body = expiry + '.form'
        self.csrf = csrf_body + '.' + self.namespace['sign']('csrf:' + csrf_body)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def post(self, data, origin='null'):
        connection = http.client.HTTPConnection(*self.server.server_address)
        connection.request('POST', '/account/password', urllib.parse.urlencode(data), {'Origin': origin, 'Cookie': 'aihub-login=' + self.session + '; aihub-csrf=' + self.csrf})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_short_password_revokes_old_sessions(self):
        status, _ = self.post({'old': self.password, 'new': 'a', 'confirm': 'a', 'csrf': self.csrf})
        self.assertEqual(status, 200)
        self.assertFalse(self.namespace['valid']('aihub-login=' + self.session))
        saved = json.loads((Path(self.temp.name) / 'account.json').read_text())
        digest = hashlib.scrypt(b'a', salt=bytes.fromhex(saved['salt']), n=16384, r=8, p=1).hex()
        self.assertEqual(saved['password_hash'], digest)

    def test_cross_site_and_bad_csrf_rejected(self):
        fields = {'old': self.password, 'new': 'a', 'confirm': 'a', 'csrf': self.csrf}
        self.assertEqual(self.post(fields, 'https://attacker.invalid')[0], 403)
        fields['csrf'] = 'invalid'
        self.assertEqual(self.post(fields)[0], 400)

    def test_old_password_and_confirmation_checked(self):
        fields = {'old': 'incorrect', 'new': 'a', 'confirm': 'a', 'csrf': self.csrf}
        self.assertEqual(self.post(fields)[0], 400)

        fields.update(old=self.password, confirm='b')
        self.assertEqual(self.post(fields)[0], 400)

    def test_mobile_form_cookie_reuse_and_recovery(self):
        connection = http.client.HTTPConnection(*self.server.server_address)
        connection.request('GET', '/login', headers={'Cookie': 'aihub-csrf=' + self.csrf})
        response = connection.getresponse()
        self.assertIn('SameSite=Lax', response.getheader('Set-Cookie'))
        self.assertIn(self.csrf.encode(), response.read())
        connection.close()
        status, page = self.post({'csrf': 'expired'})
        self.assertEqual(status, 400)
        self.assertIn(b'name="csrf"', page)

    def test_join_link_is_scoped_expiring_and_revocable(self):
        folder = Path(self.temp.name) / 'enrollment'
        (folder / 'bootstrap').mkdir(parents=True)
        command = folder / 'bootstrap/aihub-join-test.command.txt'
        command.write_text('echo 测试接入')
        token = secrets.token_urlsafe(24)
        record = {'command': str(command), 'join_token': token, 'status': 'pending', 'expires': time.time() + 60}
        def request(path):
            (folder / 'test.json').write_text(json.dumps(record))
            connection = http.client.HTTPConnection(*self.server.server_address)
            connection.request('GET', path)
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result
        path = '/join/test/' + token
        self.assertEqual(request(path), (200, command.read_bytes()))
        self.assertEqual(request('/join/test/' + 'a' * 32)[0], 404)
        self.assertEqual(request('/join/other/' + token)[0], 404)
        for status in ('cancelled', 'joined'):
            record['status'] = status
            self.assertEqual(request(path)[0], 404)
        record.update(status='pending', expires=time.time() - 1)
        self.assertEqual(request(path)[0], 404)
        record.update(expires=time.time() + 60, command='/etc/passwd')
        self.assertEqual(request(path)[0], 404)


if __name__ == '__main__':
    unittest.main()
