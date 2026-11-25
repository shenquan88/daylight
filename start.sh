#!/bin/sh
# Daylight · 向阳 — Sprite 启动脚本
# 无密钥：connector 走 Sprites 官方 OpenRouter 托管网关，不需要 token。
# 只配运行时环境变量，不写进代码、不入库。

set -e

# 项目目录：Sprite 上是 /home/sprite/daylight；本地从仓库直接跑也能用。
if [ -d /home/sprite/daylight ]; then
    cd /home/sprite/daylight
else
    cd "$(dirname "$0")"
fi

# 数据落持久磁盘：app.py 检测到 /home/sprite 会自动用 /home/sprite/daylight-data，
# 这里显式指定，避免以后目录判定变化时静默写到临时盘。
if [ -d /home/sprite ]; then
    DATA_DIR="${DAYLIGHT_DATA_DIR:-/home/sprite/daylight-data}"
    mkdir -p "$DATA_DIR"
else
    DATA_DIR="./data"
fi
set -- --port "${PORT:-8080}" --data-dir "$DATA_DIR"

# 官方 connector（Free 托管，0 美元额度）：
#   托管 connector ID = 1iRDaTyJ5VAi1NBRbliO1Q
#   仅 name_prefix = daylight，仅允许 /v1/models 与 /v1/chat/completions
export SPRITE_CONNECTOR_URL="${SPRITE_CONNECTOR_URL:-https://api.sprites.dev/v1/gateway/openrouter/1iRDaTyJ5VAi1NBRbliO1Q/v1/chat/completions}"
export SPRITE_MODEL="${SPRITE_MODEL:-liquid/lfm-3-1.7b:free}"

# 该网关不需要鉴权；若将来换成需要 token 的网关，用外部注入的
# SPRITE_CONNECTOR_TOKEN 即可，本脚本不设、不读、不落盘。
echo "Daylight: data=$DATA_DIR model=$SPRITE_MODEL"
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
exec "$PY" app.py "$@"
