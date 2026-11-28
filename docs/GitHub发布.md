# 上传至 GitHub

本地仓库名为 `aihub`，默认分支 `main`，计划创建私有仓库。仓库源码和首次部署脚本已准备；在 GitHub 官方授权完成前，不创建远程仓库或上传。

## 官方授权及发布

```bash
sudo apt install gh
gh auth login --hostname github.com --git-protocol https --web
bash scripts/publish.sh
```

按 GitHub CLI 提示在浏览器完成官方设备授权，不把 GitHub 密码、个人访问令牌或 Cookie 写入聊天及仓库。发布脚本创建当前授权账号下的私有 `aihub` 仓库并推送当前提交；检测到已有 origin 时停止，避免覆盖关联。名字已被占用时应先确认既有仓库用途，不应自动覆盖。

## 提交内容

包含部署脚本、systemd服务、统一登录、设备接入、代理管理源码、文档、测试和CI。不会提交现有服务器 profile、API Key、账号文件、SSH 私钥、FRP令牌、订阅、会话及具体设备配置；历史生产记录和草稿由 `.gitignore` 排除。

后续更新前查看 `git diff` 和 `git status`，确认没有误加入凭据。`.gitignore` 不能识别所有新命名的密钥文件，不能代替人工检查。

## 从私有仓库部署

先在目标云服务器通过 GitHub 官方方式授权，再克隆发布后显示的仓库地址，进入仓库并执行：

```bash
sudo bash scripts/install.sh --host 你的服务器公网IP或域名
```

私有仓库无法匿名 `curl` 下载安装脚本，因此“一键部署”指授权并克隆后的一条安装命令。不要把个人访问令牌嵌入下载地址。
