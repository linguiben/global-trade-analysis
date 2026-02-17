# 此脚本用于在开发环境中启动 FastAPI 进行本地调试
# cd "$(dirname "$0")"/..
# source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 9000 

#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"/..

source .venv/bin/activate

. .env
REMOTE=${REMOTE:-root@IP}  # 替换为实际的远程服务器地址和用户名
LOCAL_PORT=${POSTGRES_PORT}
LOCAL_HOST=127.0.0.1
REMOTE_PORT=${POSTGRES_PORT}

# ssh -N -L 9527:127.0.0.1:9527 root@IP
# 建立隧道（若端口转发失败则立即退出）
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 -o ServerAliveCountMax=3 -N -L ${LOCAL_PORT}:${LOCAL_HOST}:${REMOTE_PORT} ${REMOTE} &
SSH_PID=$!
sleep 3 # 等待 SSH 隧道建立

cleanup() {
  kill "$SSH_PID" 2>/dev/null || true
  wait "$SSH_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 在前台运行 uvicorn；退出时触发 cleanup
uvicorn app.main:app --host 0.0.0.0 --port 9000
