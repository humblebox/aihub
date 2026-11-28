# DSH-IM 公网管理适配

DSH-IM 5.7.0 的更新和部分设置接口固定使用本机地址校验，通过公网网页访问会返回 403。AIHub 将这两个接口的权限模式改为插件已有的 `trusted-host`，使用 Harness 原生可信主机、来源及会话校验；Nginx 的统一登录保护仍然生效。不改写请求 Host 或 Origin，也不关闭认证。

本适配只审核过 5.7.0，未改动其他渠道接口。服务必须保持监听 127.0.0.1:3080，通过受登录保护的 HTTPS 入口访问。

将仓库的 `scripts/adapt_dsh_im.py` 放到服务器后执行：

```bash
sudo python3 scripts/adapt_dsh_im.py
sudo systemctl restart aihub-harness
```

脚本会在插件 `lib` 目录备份原始 `index.js`，支持重复执行。版本或代码结构不符合预期时拒绝修改。默认路径对应 AIHub 的 web 配置，可用 `--package` 指定其他插件目录。

插件升级或重装可能覆盖适配。新版本需重新检查是否已原生支持公网管理；不要对未知版本强行替换。初始一键部署不默认安装 DSH-IM，因此此脚本按需执行，不属于默认安装步骤。

回滚时将 `index.js.aihub-backup-*` 对应备份复制回 `index.js`，再重启 `aihub-harness`。更新检查不等于安装更新；适配验证不主动升级插件。
