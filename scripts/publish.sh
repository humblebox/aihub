#!/usr/bin/env bash
# 用户完成 GitHub 官方授权后创建私有仓库并上传当前 main 分支。
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
command -v gh >/dev/null || { echo '请先安装 GitHub CLI（Ubuntu: sudo apt install gh）。'; exit 1; }
gh auth status >/dev/null 2>&1 || { echo '请先执行 gh auth login --web 完成官方授权。'; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo '请先审查并提交本地更改。'; exit 1; }
if git remote get-url origin >/dev/null 2>&1; then
  echo '已有 origin，拒绝自动改写或重复创建，请检查现有远程仓库。'
  exit 1
fi
gh repo create aihub --private --source=. --remote=origin --push
