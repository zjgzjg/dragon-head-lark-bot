#!/usr/bin/env bash
# 触发 GitHub 上的竞价 workflow（Secrets 在云端，本机只需 gh login）
set -euo pipefail
exec gh workflow run "龙头战法·竞价推送" --repo zjgzjg/dragon-head-lark-bot
