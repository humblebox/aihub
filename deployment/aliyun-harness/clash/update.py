#!/usr/bin/env python3
"""仅更新当前配置；关闭代理时不自动联网下载。"""
import fcntl
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import manage

with (manage.ROOT / 'management.lock').open('a') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(0)
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'aihub-clash']).returncode or not manage.registry()['active']:
        raise SystemExit(0)
    try:
        sys.argv = [__file__, 'refresh', '{}']
        manage.main()
    except Exception:
        # 禁止将订阅链接、节点密码等底层异常写入日志。
        print('订阅自动更新失败，继续使用现有配置。')
        raise SystemExit(1)
