#!/usr/bin/env python3
"""为 dsh-remote 1.4.1 的 OpenSSH 后端补充交互终端，保留原认证参数。"""
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path('/var/lib/aihub/.dsh/profiles/web/node_modules/dsh-remote')
NODE = Path('/opt/aihub/node-v24.22.2-linux-x64/bin/node')
MARKER = '  // AIHub：复用系统 OpenSSH 和宿主 PTY，支持终端输入及窗口缩放。'
METHOD = r'''
  // AIHub：复用系统 OpenSSH 和宿主 PTY，支持终端输入及窗口缩放。
  async shell(opts = {}) {
    await this.connect()
    const secret = await this._resolveSecret()
    const hostRequire = createRequire('/opt/aihub/node-v24.22.2-linux-x64/lib/node_modules/@deepseek-ai/dsh/package.json')
    const pty = hostRequire('node-pty')
    const args = [...baseSshArgs(this._argConfig(), { forSecret: !!secret }), '-tt', '--', this.destination()]
    const child = pty.spawn(resolveSshBinary(this.config), args, {
      name: 'xterm-256color', cols: Number(opts.cols) || 80, rows: Number(opts.rows) || 24,
      cwd: homedir(), env: { ...process.env, ...(secret ? askpassEnv(secret) : {}), TERM: 'xterm-256color' },
    })
    let ended = false
    const stream = new Duplex({
      read() {},
      write(data, encoding, callback) {
        try { child.write(data.toString()); callback() } catch (error) { callback(error) }
      },
      final(callback) { if (!ended) child.kill(); callback() },
      destroy(error, callback) { if (!ended) child.kill(); callback(error) },
    })
    child.onData(data => stream.push(Buffer.from(data)))
    child.onExit(() => { ended = true; stream.push(null); stream.destroy() })
    stream.setWindow = (rows, cols) => { if (!ended) child.resize(cols, rows) }
    stream.close = () => stream.destroy()
    return stream
  }
'''


def main():
    if json.loads((ROOT / 'package.json').read_text())['version'] != '1.4.1':
        raise SystemExit('仅适配已验证的 1.4.1，其他版本需重新检查。')
    path = ROOT / 'lib/openssh.js'
    source = path.read_text()
    if MARKER in source:
        print('终端适配已存在。')
        return
    anchor = '  /** Validate the environment; there is no socket to hold open. */'
    if source.count(anchor) != 1 or '  async shell(' in source:
        raise SystemExit('插件结构变化，未修改。')
    candidate = path.with_suffix('.aihub-check.mjs')
    try:
        candidate.write_text(source.replace(anchor, METHOD + '\n' + anchor))
        subprocess.run([str(NODE), '--check', str(candidate)], check=True)
        backup = path.with_suffix('.js.before-aihub-terminal')
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(candidate.read_text())
    finally:
        candidate.unlink(missing_ok=True)
    print('OpenSSH 交互终端适配完成。')


if __name__ == '__main__':
    main()
