#!/usr/bin/env python3
"""适配 DSH-IM 5.7.0 管理接口，沿用 Harness 可信主机和原生会话认证。"""
import argparse
import json
from pathlib import Path
import shutil
import time


def adapt(package):
    package = Path(package)
    if json.loads((package / 'package.json').read_text())['version'] != '5.7.0':
        raise ValueError('仅验证过 DSH-IM 5.7.0；其他版本需重新审核，未修改文件。')
    target = package / 'lib/index.js'
    source = target.read_text()
    updated = source
    for name in ('Nme', 'Ywe'):
        start = updated.index('function ' + name + '(')
        end = updated.index('}var ' if name == 'Ywe' else '}import', start)
        block = updated[start:end]
        old = '{authority:"loopback"}'
        new = '{authority:"trusted-host"}'
        if block.count(old) + block.count(new) != 1:
            raise ValueError('接口结构与审核版本不同，未修改文件。')
        updated = updated[:start] + block.replace(old, new) + updated[end:]
    if updated == source:
        print('管理接口已适配，无需重复修改。')
        return
    backup = target.with_name('index.js.aihub-backup-' + str(time.time_ns()))
    shutil.copy2(target, backup)
    target.write_text(updated)
    print('管理接口适配完成，原文件已在同目录备份。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', default='/var/lib/aihub/.dsh/profiles/web/node_modules/@xmanrui/dsh-im')
    adapt(parser.parse_args().package)
