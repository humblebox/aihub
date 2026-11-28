#!/usr/bin/env python3
"""在云服务器接入现成面板，控制密钥仅写入 root 可读的 Nginx 配置。"""
from pathlib import Path
import os
import yaml
import zipfile

with zipfile.ZipFile('/tmp/zashboard-gh-pages.zip') as archive:
    target = Path('/opt/aihub/zashboard')
    target.mkdir(parents=True, exist_ok=True)
    for entry in archive.infolist():
        if entry.is_dir():
            continue
        relative = Path(entry.filename)
        if relative.parts[0] in ('dist', 'zashboard-gh-pages'):
            relative = Path(*relative.parts[1:])
        dest = target / relative
        if not dest.resolve().is_relative_to(target.resolve()):
            raise ValueError('压缩包路径不正确')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive.read(entry))
        dest.chmod(0o644)
    for folder, _, _ in os.walk(target):
        Path(folder).chmod(0o755)

secret = yaml.safe_load(Path('/var/lib/aihub-clash/config.yaml').read_text())['secret']
conf = Path('/etc/nginx/aihub-clash-secret.conf')
conf.write_text('proxy_set_header Authorization "Bearer ' + secret + '";\n')
conf.chmod(0o600)
locations = '''
 # 完整代理面板与控制接口均沿用 AI 网页会话。
 location = /_aihub_clash_auth {
  internal;
  proxy_pass http://127.0.0.1:3080/api/aihub-clash/auth;
  proxy_pass_request_body off;
  proxy_set_header Content-Length "";
  proxy_set_header Host $http_host;
  proxy_set_header Origin $http_origin;
  proxy_set_header Cookie $http_cookie;
 }
 location = /clash/dashboard { return 302 /clash/dashboard/; }
 location /clash/dashboard/ {
  auth_request /_aihub_clash_auth;
  alias /opt/aihub/zashboard/;
  index index.html;
  add_header Cache-Control "no-store" always;
 }
 location /clash/controller/ {
  auth_request /_aihub_clash_auth;
  proxy_pass http://127.0.0.1:9090/;
  proxy_http_version 1.1;
  include /etc/nginx/aihub-clash-secret.conf;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_read_timeout 3600;
  proxy_buffering off;
  add_header Cache-Control "no-store" always;
 }
'''
site = Path('/etc/nginx/sites-available/aihub')
text = site.read_text()
if 'location /clash/controller/' not in text:
    site.with_name('aihub.before-dashboard').write_text(text)
    site.write_text(text.replace(' location / {', locations + '\n location / {'))
print('完整面板文件及受保护路由已安装')
