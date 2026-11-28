# AIHub

将 DeepSeek Harness 部署为云端 AI 工作台，通过浏览器使用多个模型厂商或中转站 API，并用 SSH + FRP 在多台远程电脑执行任务。提供固定账号登录、多设备接入、多工作区，以及可选使用的 Mihomo 代理与 Zashboard 面板。

本项目是 Harness 的部署集成与扩展，不是模型服务本身，也不是 Clash Verge 网页移植版。

## 功能

- 统一账号密码登录与修改密码，自动衔接 Harness 原生认证。
- 通过现成适配器接入 OpenAI Responses、Chat Completions、Anthropic Messages 等协议。
- 按实际模型配置图片输入能力及推理等级。
- 使用现成 [dsh-remote](https://github.com/flymysql/dsh-remote) 管理远程设备及工作区。
- 网页生成 Linux、Windows、安卓接入命令，目标设备使用当前终端目录作为默认工作区。
- 多份 Clash／Mihomo 配置保存、切换与更新，现成 [Zashboard](https://github.com/Zephyruso/zashboard) 管理代理策略和测速。
- 中文部署说明、systemd 服务与 GitHub Actions 基础检查。

## 一键部署

要求：**全新 Ubuntu 22.04 或 24.04 x86_64、root/sudo、systemd**。建议至少2核2GB，有可用公网 IPv4 或已解析域名，并能访问 npm、Node 官方下载及 GitHub。暂不支持 ARM、Docker 生产部署或在现有安装上覆盖升级。

克隆本仓库后，在服务器执行：

```bash
sudo bash scripts/install.sh --host 你的公网IP或域名
```

脚本自动安装 Node、全局 Harness、FRP、Mihomo、网页面板、统一登录及设备接入服务，生成独立随机凭据和自签名 HTTPS 证书。Harness 仅安装一份，由 systemd 管理，不使用虚拟环境；插件和运行数据保存在 `/var/lib/aihub/.dsh`。已有 `/opt/aihub` 或运行数据时拒绝覆盖。

安装完成后：

1. 在云安全组放行 TCP **443、7000**，保留 SSH **22** 供管理与设备首次注册使用。
2. 在服务器运行 `sudo cat /root/aihub-initial-login.txt` 查看本次安装生成的账号信息。
3. 打开 `https://你的主机/login`，接受自行管理的自签名证书后登录。
4. 在“设置 → 模型”填写 API 和模型信息。安装器不包含任何个人中转站、API Key 或现有设备。
5. 在“设置 → 添加远程设备”生成命令，去目标电脑项目目录执行。

私有仓库需要先通过 GitHub 官方方式授权克隆；不要在 `curl` 命令或聊天中粘贴个人 Token。脚本执行前可查看 `scripts/install.sh --help` 和 [部署指南](docs/部署指南.md)。

## 常用入口

以 `https://你的主机` 为前缀：

| 路径 | 用途 |
| --- | --- |
| `/login` | 固定登录页 |
| `/` | AI 工作台 |
| `/account/password` | 修改密码，修改后各设备需重新登录 |
| `/devices` | 生成目标设备接入命令 |
| `/clash` | 订阅配置和代理服务开关 |
| `/clash/dashboard/` | 完整面板；推荐从 `/clash` 页内入口进入，自动填写连接参数 |

新密码允许1个字符，不要求字符组合；不能为空且两次输入一致。登录服务保存密码哈希，修改后不记录新密码明文。初始密码文件不会自动变成新密码。

## 远程工作流程

设备接入无需与服务器位于同一局域网。目标电脑通过 frpc 主动连接云端，然后 Harness 用 SSH 工具执行任务。目标端仍需安装 SSH 和 frpc；接入命令会自动完成配置，并不意味着完全没有客户端。

Linux 使用 Ubuntu／Debian x86_64，初次安装需 sudo。Windows 使用管理员 PowerShell 和 Git Bash；安卓使用 Termux，可能受后台策略限制。Windows／安卓尚待完整实机验证。

新建会话时选择远程设备和有权限访问的工作区。接入时的当前目录只是初始值，后续可添加其他绝对路径。普通文件视图可能显示云端镜像，远程文件视图显示目标实时内容；使用 `rw_exec` 执行远程命令，`rw_sync` 下载、`rw_push` 上传，自动推送默认关闭。

## 模型与插件

模型能力取决于真实 API，不由名称自动保证。手动添加的视觉模型应声明 `input: [text, image]`，推理档位需按服务商实际支持设置。YAML 中推理键 `'off'` 必须保持字符串，避免被解析为布尔值。

插件运行在服务器账号权限下。已知 Harness `0.2.1-rc.5` 某些在线启停会触发 `HMR transactions cannot be nested`；本项目未声称修复上游所有热更新问题。启动类插件变更需保留 SSH 恢复入口，不需要额外安装替代网页启动组件的远程访问插件。

## 代理范围

云端代理仅监听 `127.0.0.1:7890`，控制接口为 `127.0.0.1:9090`。打开代理服务不等于自动配置 AI、操作系统或远程电脑的代理。订阅保留节点、策略组和规则，但不接管监听设置、密钥、脚本或 TUN。

## 文档和维护

- [部署、端口、目录与恢复](docs/部署指南.md)
- [终端停止、启动、重启 Harness 与查看日志](docs/部署指南.md#终端停止启动和重启-harness)
- [GitHub 官方授权与私有仓库发布](docs/GitHub发布.md)
- [统一登录实现](deployment/aliyun-harness/login/README.md)
- [网页设备接入](deployment/aliyun-harness/web-enrollment/README.md)
- [终端接入机制](deployment/aliyun-harness/enrollment/README.md)
- [Windows 和安卓](deployment/aliyun-harness/enrollment/跨平台接入.md)
- [云端代理](deployment/aliyun-harness/clash/README.md)

本地检查：

```bash
bash -n scripts/install.sh
python3 -m compileall -q scripts deployment/aliyun-harness tests
python3 -m unittest discover -s tests -v
```

代码不包含运行中的 profile、账号、SSH 私钥、FRP 令牌、订阅或模型密钥。历史机器专用配置和未启用草稿不提交。第三方组件许可归各上游所有。

## 验证范围

现有部署已验证 Linux 远程命令与文件、统一登录、多配置切换、代理出网和订阅更新。安装脚本提供语法检查及安装后端到端健康检查；已在Ubuntu24.04 systemd隔离环境验证新配置生成、服务启动、登录及页面访问、设备接入命令生成；官方资产下载部分受网络限制，使用同版本缓存补齐测试，详情见部署文档。Windows／安卓、所有模型图片能力和所有推理档位未逐项验证。
