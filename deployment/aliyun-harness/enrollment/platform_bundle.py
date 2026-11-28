#!/usr/bin/env python3
"""生成 Windows／安卓安装包和终端启动命令。"""
import base64
import io
import json
from pathlib import Path
import shlex
import zipfile


def windows_bundle(base, info, hostkey):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('enroll_key', 'authorized.pub', 'frpc.exe', 'frpc.toml', 'cloud_known_hosts', 'info.json', 'join_windows.ps1'):
            if name.endswith('.ps1'):
                z.writestr(name, (base / name).read_text().encode('utf-8-sig'))
            else:
                z.write(base / name, name)
    # 使用 SSH Base64 文本下载，避免 PowerShell 5.1 原生程序输出损坏二进制。
    key = base64.b64encode((base / 'enroll_key').read_bytes()).decode()
    known = base64.b64encode((hostkey + '\n').encode()).decode()
    bootstrap = f'''$ErrorActionPreference='Stop'
if(-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){{throw '请在管理员 PowerShell 中执行'}}
$Workspace=(Get-Location).Path
$Ssh=Join-Path $env:WINDIR 'System32\\OpenSSH\\ssh.exe'
if(-not(Test-Path $Ssh)){{Add-WindowsCapability -Online -Name 'OpenSSH.Client~~~~0.0.1.0'|Out-Null}}
$Temp=Join-Path $env:TEMP ('aihub-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Temp|Out-Null
try{{
$Key=Join-Path $Temp 'enroll_key'
[IO.File]::WriteAllBytes($Key,[Convert]::FromBase64String('{key}'))
$Who=[Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls.exe $Key /inheritance:r /grant:r ($Who+':F')|Out-Null
$Known=Join-Path $Temp 'cloud_known_hosts'
[IO.File]::WriteAllBytes($Known,[Convert]::FromBase64String('{known}'))
$Data=& $Ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 -o ('UserKnownHostsFile='+$Known) -i $Key root@{info['server']} download
if($LASTEXITCODE -ne 0){{throw '安装包下载失败或凭据已过期'}}
$Zip=Join-Path $Temp 'bundle.zip'
[IO.File]::WriteAllBytes($Zip,[Convert]::FromBase64String(($Data -join '')))
Expand-Archive -LiteralPath $Zip -DestinationPath $Temp -Force
& (Join-Path $Temp 'join_windows.ps1') -Workspace $Workspace -Bundle $Zip
}}finally{{Remove-Item -LiteralPath $Temp -Recurse -Force -ErrorAction SilentlyContinue}}
'''
    command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + base64.b64encode(bootstrap.encode('utf-16le')).decode() + '\n'
    return base64.b64encode(payload.getvalue()).decode(), command


def android_command(bootstrap):
    # Termux 包由其仓库提供，避免误用普通 Linux 的 glibc 可执行文件。
    bootstrap = bootstrap.replace("shutil.which('ssh') or subprocess.run(['sudo','apt-get','install','-y','openssh-client'],check=True);", "shutil.which('ssh') or subprocess.run(['pkg','install','-y','openssh'],check=True);")
    return 'pkg install -y python openssh && python -c ' + shlex.quote(bootstrap) + '\n'
