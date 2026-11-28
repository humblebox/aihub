"""验证管理接口适配的版本限制和失败时不写入。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('adapter', Path(__file__).resolve().parents[1] / 'scripts/adapt_dsh_im.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class AdapterTests(unittest.TestCase):
    def test_version_and_structure_fail_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder)
            (package / 'lib').mkdir()
            target = package / 'lib/index.js'
            original = 'function Nme(n){return f({authority:"loopback"})}import x;function Ywe(n){unknown()}var x;'
            target.write_text(original)
            for version in ('5.8.0', '5.7.0'):
                (package / 'package.json').write_text(json.dumps({'version': version}))
                with self.assertRaises(ValueError):
                    adapter.adapt(package)
                self.assertEqual(target.read_text(), original)
                self.assertEqual(list((package / 'lib').glob('*backup*')), [])

    def test_idempotent_and_preserves_other_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder)
            (package / 'lib').mkdir()
            (package / 'package.json').write_text('{"version":"5.7.0"}')
            target = package / 'lib/index.js'
            original = 'function Nme(n){f({authority:"loopback"})}import x;function Ywe(n){f({authority:"loopback"})}var x;f({authority:"loopback"});'
            target.write_text(original)
            adapter.adapt(package)
            adapter.adapt(package)
            self.assertEqual(target.read_text().count('authority:"trusted-host"'), 2)
            self.assertEqual(target.read_text().count('authority:"loopback"'), 1)
            backups = list((package / 'lib').glob('*backup*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)
