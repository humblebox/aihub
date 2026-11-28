# 在管理员 PowerShell 中配置 Windows 远程工作区。
param([string]$Workspace = (Get-Location).Path, [string]$Bundle)
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw '请在管理员 PowerShell 中执行，并先进入希望 AI 操作的项目目录。' }
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw '当前仅支持 Windows 10/11 x64。' }
if (-not (Test-Path -LiteralPath $Workspace -PathType Container) -or $Workspace -notmatch '^[A-Za-z]:\\') { throw '项目必须位于本机磁盘，请勿使用 UNC 网络路径。' }
$Base = Split-Path -Parent $Bundle
$Info = Get-Content -Raw -LiteralPath (Join-Path $Base 'info.json') | ConvertFrom-Json
if ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -gt $Info.expires) { throw '接入命令已过期。' }
$SshAccount = & (Join-Path $env:WINDIR 'System32\whoami.exe')
if ($SshAccount -notmatch ('^' + [regex]::Escape($env:COMPUTERNAME) + '\\')) { throw '当前自动接入只支持本机 Windows 账户，不支持域账户或 Microsoft 在线账户；请切换本机账户。' }
$GitBash = Join-Path $env:ProgramFiles 'Git\bin\bash.exe'
if (-not (Test-Path $GitBash)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw '未找到 Git Bash 和 winget。请先安装 Git for Windows，再重新执行接入命令。' }
    & winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $GitBash)) { throw 'Git Bash 安装失败，请先安装 Git for Windows。' }
}
$Capability = Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
if ($Capability.State -ne 'Installed') { Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null }
Set-Service sshd -StartupType Automatic
Start-Service sshd
# 管理员账户默认使用系统管理员公钥文件，保留已有配置和公钥。
& (Join-Path $env:WINDIR 'System32\OpenSSH\ssh-keygen.exe') -A
$SshConfig = Join-Path $env:ProgramData 'ssh\sshd_config'
$ConfigText = Get-Content -Raw -LiteralPath $SshConfig
if ($ConfigText -notmatch '(?im)^\s*Match Group administrators\s*$' -or $ConfigText -notmatch '(?im)^\s*AuthorizedKeysFile\s+__PROGRAMDATA__/ssh/administrators_authorized_keys\s*$') { throw '当前 SSH 使用自定义管理员公钥路径，请先核验 sshd_config 后再接入。' }
$Authorized = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
$Pub = (Get-Content -Raw -LiteralPath (Join-Path $Base 'authorized.pub')).Trim()
if (-not (Test-Path $Authorized)) { [IO.File]::WriteAllText($Authorized, '', [Text.UTF8Encoding]::new($false)) }
if (-not ([IO.File]::ReadAllText($Authorized).Contains($Pub))) { [IO.File]::AppendAllText($Authorized, "`r`nrestrict,port-forwarding,pty $Pub`r`n", [Text.UTF8Encoding]::new($false)) }
& icacls.exe $Authorized /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw '设置管理员 SSH 公钥权限失败。' }
$Target = Join-Path $env:ProgramData ('AIHub\' + $Info.id)
New-Item -ItemType Directory -Force -Path $Target | Out-Null
& icacls.exe $Target /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw '设置连接配置权限失败。' }
Copy-Item -LiteralPath (Join-Path $Base 'frpc.exe') -Destination (Join-Path $Target 'frpc.exe') -Force
Copy-Item -LiteralPath (Join-Path $Base 'frpc.toml') -Destination (Join-Path $Target 'frpc.toml') -Force
$Frpc = Join-Path $Target 'frpc.exe'
$FrpcConfig = Join-Path $Target 'frpc.toml'
& $Frpc verify -c $FrpcConfig
if ($LASTEXITCODE -ne 0) { throw 'FRP 配置校验失败。' }
$Action = New-ScheduledTaskAction -Execute $Frpc -Argument ('-c "' + $FrpcConfig + '"')
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$TaskName = 'AIHub-frpc-' + $Info.id
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
$Key = Join-Path $Base 'enroll_key'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $Key /inheritance:r /grant:r ($Identity + ':F') | Out-Null
$Payload = @{user=$env:USERNAME;workspace=$Workspace.Replace('\','/');hostkey=([IO.File]::ReadAllText((Join-Path $env:ProgramData 'ssh\ssh_host_ed25519_key.pub'))).Trim()} | ConvertTo-Json -Compress
$Ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$SshArgs = @('-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=8','-o',('UserKnownHostsFile='+(Join-Path $Base 'cloud_known_hosts')),'-i',$Key,('root@'+$Info.server),'register')
# 以 UTF-8 明确写入标准输入，避免中文路径在旧版 PowerShell 管道中变成问号。
for ($Attempt=0; $Attempt -lt 15; $Attempt++) {
    $Start = New-Object Diagnostics.ProcessStartInfo
    $Start.FileName=$Ssh
    $Start.Arguments=($SshArgs | ForEach-Object { '"' + $_.Replace('"','\"') + '"' }) -join ' '
    $Start.UseShellExecute=$false; $Start.RedirectStandardInput=$true; $Start.RedirectStandardOutput=$true; $Start.RedirectStandardError=$true
    $Start.StandardInputEncoding=[Text.UTF8Encoding]::new($false)
    $Process=[Diagnostics.Process]::Start($Start)
    $Process.StandardInput.Write($Payload); $Process.StandardInput.Close()
    $Out=$Process.StandardOutput.ReadToEnd(); $Err=$Process.StandardError.ReadToEnd(); $Process.WaitForExit()
    if ($Process.ExitCode -eq 0) { Write-Host $Out; Write-Host 'Windows 接入成功，网页远程工作区刷新后选择设备即可。'; return }
    Start-Sleep -Seconds 2
}
throw ('注册失败，已安装的 SSH／FRP 保留，可在有效期内重试：' + $Err)
