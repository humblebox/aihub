"""验证日志轮转后认证仍可用，并拒绝复用旧服务实例令牌。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('harness_auth', Path(__file__).resolve().parents[1] / 'deployment/aliyun-harness/login/harness_auth.py')
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)


class AuthCacheTests(unittest.TestCase):
    def test_rotated_logs_and_changed_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'auth.json'
            url = 'http://127.0.0.1:3080/?token=test-private-token'
            with patch.object(auth, 'CACHE', cache), patch.object(auth, 'invocation', return_value='a' * 32), patch.object(auth.subprocess, 'run') as run:
                run.return_value.stdout = 'dsh web: ' + url
                self.assertEqual(auth.resolve(), url)
                self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
                run.reset_mock()
                self.assertEqual(auth.resolve(), url)
                run.assert_not_called()
            with patch.object(auth, 'CACHE', cache), patch.object(auth, 'invocation', return_value='b' * 32), patch.object(auth.subprocess, 'run') as run:
                run.return_value.stdout = ''
                with self.assertRaises(RuntimeError):
                    auth.resolve()

    def test_only_loopback_entry_allowed(self):
        for url in ['https://other.example/?token=x', 'http://127.0.0.1:3080/', 'http://127.0.0.1:3080/connect?token=x']:
            self.assertFalse(auth.valid_url(url))
