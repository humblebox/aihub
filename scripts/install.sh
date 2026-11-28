#!/usr/bin/env bash
# 在干净的 Ubuntu 22.04/24.04 x86_64 服务器部署 AIHub。
set -Eeuo pipefail
umask 077
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == "--help" ]]; then
  cat <<'HELP'
使用：sudo bash scripts/install.sh --host 公网IP或域名
可选环境变量：AIHUB_ADMIN_USER（默认 admin）
安装后随机密码写入 /root/aihub-initial-login.txt；API 在网页中设置。
仅适用于未安装 AIHub 的 Ubuntu 22.04/24.04 x86_64；已有部署不会覆盖。
开放安全组 TCP 22、443、7000。默认 HTTPS 为自签名证书。
HELP
  exit 0
fi
[[ $EUID -eq 0 ]] || { echo '请使用 sudo 运行。'; exit 1; }
[[ "${1:-}" == "--host" && -n "${2:-}" && $# -eq 2 ]] || { echo '用法：sudo bash scripts/install.sh --host 公网IP或域名'; exit 1; }
AIHUB_HOST="$2"
export AIHUB_HOST
python3 - <<'PY'
import os,re
host=os.environ['AIHUB_HOST']
if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?',host) or '..' in host:
    raise SystemExit('仅支持 IPv4 地址或域名，不含协议、路径和端口。')
PY
source /etc/os-release
[[ "$ID" == ubuntu && ( "$VERSION_ID" == 22.04 || "$VERSION_ID" == 24.04 ) && "$(uname -m)" == x86_64 ]] || { echo '仅支持 Ubuntu 22.04/24.04 x86_64。'; exit 1; }
[[ ! -e /opt/aihub && ! -e /var/lib/aihub && ! -e /etc/nginx/sites-available/aihub ]] || { echo '检测到已有 AIHub 文件，拒绝覆盖。请先备份并使用升级流程。'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl xz-utils unzip nginx openssl python3 python3-yaml openssh-server git build-essential python3-dev iproute2
systemctl enable --now ssh
install -d -m 755 /opt/aihub /opt/aihub/downloads
printf '安装固定版本 Node、Harness、远程插件及代理核心…\n'
NODE_VERSION=24.22.2
FRP_VERSION=0.71.1
MIHOMO_VERSION=1.19.29
ZASHBOARD_VERSION=3.30.0
TASK_TMP="$(mktemp -d)"
trap 'rm -rf "$TASK_TMP"' EXIT
fetch() {
  local cached_name="${1##*/}"
  if [[ -n "${AIHUB_DOWNLOAD_CACHE:-}" && -f "$AIHUB_DOWNLOAD_CACHE/$cached_name" ]]; then
    cp -- "$AIHUB_DOWNLOAD_CACHE/$cached_name" "$2"
  else
    curl --fail --location --silent --show-error --retry 3 --connect-timeout 20 --max-time 600 "$1" -o "$2"
  fi
}
fetch "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" "$TASK_TMP/node.tar.xz"
fetch "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" "$TASK_TMP/SHASUMS256.txt"
python3 - "$TASK_TMP" "$NODE_VERSION" <<'PY'
import hashlib,sys
from pathlib import Path
p=Path(sys.argv[1]);name='node-v'+sys.argv[2]+'-linux-x64.tar.xz'
expected=next(line.split()[0] for line in (p/'SHASUMS256.txt').read_text().splitlines() if line.split()[-1]==name)
assert hashlib.sha256((p/'node.tar.xz').read_bytes()).hexdigest()==expected,'Node 校验失败'
PY
tar -xJf "$TASK_TMP/node.tar.xz" -C /opt/aihub
export PATH="/opt/aihub/node-v${NODE_VERSION}-linux-x64/bin:$PATH"
export npm_config_nodedir="/opt/aihub/node-v${NODE_VERSION}-linux-x64"
npm install -g pnpm@10.11.0
# Harness 只安装全局版本；插件、会话及凭据继续保存在独立数据目录。
npm install -g @deepseek-ai/dsh@0.2.2-rc.5 --legacy-peer-deps --no-audit --no-fund --allow-scripts=@deepseek-ai/dsh-subprocess-local,koffi,node-pty,@google/genai,protobufjs
for task_binary in node npm npx dsh; do
  ln -sfn "/opt/aihub/node-v${NODE_VERSION}-linux-x64/bin/$task_binary" "/usr/local/bin/$task_binary"
done
fetch "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz" "$TASK_TMP/frp.tar.gz"
tar -xzf "$TASK_TMP/frp.tar.gz" -C "$TASK_TMP"
install -d /opt/aihub/frp
install -m 755 "$TASK_TMP/frp_${FRP_VERSION}_linux_amd64/frps" "$TASK_TMP/frp_${FRP_VERSION}_linux_amd64/frpc" /opt/aihub/frp/
fetch "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_windows_amd64.zip" "$TASK_TMP/frp-win.zip"
python3 - "$TASK_TMP/frp-win.zip" <<'PY'
import zipfile,sys
from pathlib import Path
with zipfile.ZipFile(sys.argv[1]) as z:
    name=next(n for n in z.namelist() if n.endswith('/frpc.exe'))
    Path('/opt/aihub/downloads/frpc-windows.exe').write_bytes(z.read(name))
PY
fetch "https://github.com/MetaCubeX/mihomo/releases/download/v${MIHOMO_VERSION}/mihomo-linux-amd64-v${MIHOMO_VERSION}.gz" "$TASK_TMP/mihomo.gz"
gzip -dc "$TASK_TMP/mihomo.gz" > /usr/bin/verge-mihomo
chmod 755 /usr/bin/verge-mihomo
fetch "https://github.com/Zephyruso/zashboard/releases/download/v${ZASHBOARD_VERSION}/dist-no-fonts.zip" /tmp/zashboard-gh-pages.zip
# GEOIP 订阅规则会使用该数据库，禁止安装时依赖个人电脑上的文件。
fetch 'https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/country.mmdb' "$TASK_TMP/Country.mmdb"
python3 "$ROOT_DIR/scripts/provision.py" --source "$ROOT_DIR" --host "$AIHUB_HOST" --country "$TASK_TMP/Country.mmdb"
nginx -t
runuser -u aihub-clash -- /usr/bin/verge-mihomo -t -d /var/lib/aihub-clash -f /var/lib/aihub-clash/config.yaml
systemctl daemon-reload
systemctl enable --now aihub-harness aihub-login aihub-enrollment aihub-frps aihub-clash aihub-clash-update.timer
systemctl enable nginx
systemctl reload nginx
python3 "$ROOT_DIR/scripts/healthcheck.py" --host "$AIHUB_HOST"
printf '\n部署完成。固定地址：https://%s/login\n账号信息：/root/aihub-initial-login.txt（不要公开）\n请在安全组开放 TCP 443、7000，设备注册同时需要 TCP 22。\n' "$AIHUB_HOST"
