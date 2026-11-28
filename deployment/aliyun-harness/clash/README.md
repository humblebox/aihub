# 云服务器代理管理

## 日常使用

先登录 AI 网页，打开 `https://你的服务器/clash`。此入口显示订阅配置和服务开关，页面顶部「进入完整代理面板」打开现成的 [Zashboard](https://github.com/Zephyruso/zashboard) 并填写同源控制地址。节点选择、模式、策略组、测速、规则、连接、流量和日志使用上游面板实现，不再使用自制的代理页面。

Zashboard 是 Mihomo 网页面板，不是 Clash Verge 桌面程序。Clash Verge 无法直接作为网页运行；若需要完全一致的桌面界面，需要另外部署图形桌面及远程桌面访问，本项目当前没有启用这一方案。

## 订阅与开关

`https://你的服务器/clash` 提供订阅和后台服务管理，旧的 `/clash/configuration` 地址重定向至此，AI 网页的「Clash 代理」设置中也有两个入口。

- 保存多份配置，支持切换、更新、改名及删除。切换使用本地缓存。
- 订阅链接明文显示，仅在登录后加载，文件使用 0600 权限。
- 当前配置必须切换后才能删除，相同链接更新已有配置。
- 保留订阅原有节点、策略组和规则，不额外加入 Proxy 策略组或强制改写全局模式选择。
- 只有订阅没有策略组时，才创建包含节点的默认 Proxy 选择组。
- 服务器端口、密钥和 TUN 保持服务器管理值，不导入订阅的监听设置、脚本或外部文件提供者。
- 本页不定时刷新和重建交互控件；需要时手动刷新状态，操作完成后刷新。
- 关闭服务会停止核心并取消开机启动；开启时恢复。代理只作用于云服务器。

## 服务与文件

后台核心复用已安装的 `/usr/bin/verge-mihomo`，服务为 `aihub-clash`，专用用户为 `aihub-clash`。核心配置在 `/var/lib/aihub-clash/config.yaml`，多配置记录在 `profiles.json`，缓存位于 `profiles` 子目录。配置包含订阅地址和节点凭据，不应公开。

HTTP / SOCKS5 代理为 `127.0.0.1:7890`，控制接口为 `127.0.0.1:9090`，均不对外监听。AI 服务没有自动配置使用代理，未启用系统代理或 TUN。需要代理的应用应分别配置。

```bash
systemctl status aihub-clash --no-pager
systemctl restart aihub-clash
HTTPS_PROXY=http://127.0.0.1:7890 curl -I https://github.com
```

`aihub-clash-update.timer` 每小时更新当前配置。下载首先尝试当前代理，再尝试直连；服务关闭时跳过。下载或校验失败保留旧配置。订阅更新、切换共用管理锁。

## 网页面板部署

上游静态构建来自官方 `gh-pages` 分支，保留上游构建和许可。静态文件位于 `/opt/aihub/zashboard`，不修改其代理交互实现。`install_dashboard.py` 要求压缩包位于 `/tmp/zashboard-gh-pages.zip`。

Nginx 对 `/clash/dashboard/` 和 `/clash/controller/` 使用 `auth_request` 校验 AI 登录会话。控制密钥保存在 root 可读的 `/etc/nginx/aihub-clash-secret.conf`，由 Nginx 注入上游，不需要在浏览器填写。

## 验证记录

默认入口显示订阅与开关、页内链接进入现成面板、面板首页静态资源、独立配置页面、节点／规则／连接接口及登录保护已验证。当前配置与保存的订阅保持同样的 9 个策略组和 9263 条规则，未添加 Proxy 组；策略组选择接口已验证。此前已验证流量和日志 WebSocket、64 个节点导入、云端代理联网返回 204、代理下载订阅和多配置切换。当前环境无可用浏览器会话，尚未进行浏览器交互及视觉验证。
