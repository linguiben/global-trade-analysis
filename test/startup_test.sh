# 此脚本用于在开发环境中启动 FastAPI 进行本地调试

cd "$(dirname "$0")"/..

source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 9000

