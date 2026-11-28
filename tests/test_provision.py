"""验证生成配置使用部署主机而非个人服务器，且不会引入生产凭据。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import importlib.util
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ProvisionTests(unittest.TestCase):
    def test_provision_generates_host_bound_private_config(self):
        spec = importlib.util.spec_from_file_location('provision', ROOT / 'scripts/provision.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            real_path = Path
            real_copytree = module.shutil.copytree
            real_copyfile = module.shutil.copyfile

            def mapped(value):
                text = str(value)
                return target / text.lstrip('/') if text.startswith(('/opt/', '/etc/', '/var/', '/root/')) else real_path(value)

            def write(path, text, mode=0o600, user=None):
                path = mapped(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                path.chmod(mode)

            def copytree(source, destination, **kwargs):
                return real_copytree(source, mapped(destination), **kwargs)

            def copyfile(source, destination, **kwargs):
                destination = mapped(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                return real_copyfile(source, destination, **kwargs)

            country = target / 'Country.mmdb'
            country.write_bytes(b'test')
            with patch.object(module, 'Path', side_effect=mapped), patch.object(module, 'write', side_effect=write), patch.object(module, 'command'), patch.object(module.shutil, 'copytree', side_effect=copytree), patch.object(module.shutil, 'copyfile', side_effect=copyfile), patch.object(module.pwd, 'getpwnam', return_value=object()):
                # openssl 在此隔离测试中不执行，预建待校验的私钥路径。
                key = target / 'etc/aihub/tls/server.key'
                key.parent.mkdir(parents=True)
                key.touch()
                module.provision(ROOT, 'test.example.com', country)
            profile = target / 'var/lib/aihub/.dsh/profiles/web'
            config = yaml.safe_load((profile / 'cordis.patch.yml').read_text())
            self.assertEqual(config[0]['config']['trustedHosts'], ['test.example.com'])
            account = json.loads((target / 'var/lib/aihub-login/account.json').read_text())
            self.assertEqual(account['username'], 'admin')
            self.assertNotIn('password', account)
            self.assertTrue((target / 'var/lib/aihub/.ssh/config').exists())
            manifest = json.loads((profile / 'package.json').read_text())
            self.assertEqual(manifest['dependencies']['dsh-remote'], '0.8.71')
            self.assertFalse((profile / 'node_modules/dsh-remote').is_symlink())
            unit = (target / 'etc/systemd/system/aihub-harness.service').read_text()
            self.assertIn('/lib/node_modules/@deepseek-ai/dsh/lib/bin.js', unit)
            self.assertNotIn('/opt/aihub/harness/', unit)
            nginx = (target / 'etc/nginx/sites-available/aihub').read_text()
            self.assertIn('server_name test.example.com;', nginx)
            self.assertEqual([line.strip() for line in nginx.splitlines() if line.strip().startswith('server_name ')], ['server_name test.example.com;'])


if __name__ == '__main__':
    unittest.main()
