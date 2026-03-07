#!/bin/bash
# ============================================================
#  NetMonitor Server — Linux 一键安装脚本
#  适用：Ubuntu 20.04+ / Debian 11+ / 其他主流 Linux
#  用法：bash install_server.sh
# ============================================================

set -e

REPO="https://github.com/secure-artifacts/networkhome.git"
INSTALL_DIR="/opt/netmonitor-server"
SERVICE_NAME="netmonitor-server"
PORT=8866

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERR]${NC}   $*"; exit 1; }

echo ""
echo "============================================================"
echo "   NetMonitor Server — Linux 安装程序 v2.0.2"
echo "============================================================"
echo ""

# ── 检查 root ──────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "请使用 sudo 运行此脚本：sudo bash install_server.sh"
fi

# ── 检查依赖 ──────────────────────────────────────────
info "检查系统依赖..."
for cmd in git python3 pip3; do
    if ! command -v $cmd &>/dev/null; then
        warn "未找到 $cmd，正在安装..."
        apt-get update -qq && apt-get install -y git python3 python3-pip python3-venv
        break
    fi
done

PYTHON=$(command -v python3)
PYVER=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Python 版本: $PYVER"

# ── 拉取源码 ──────────────────────────────────────────
info "拉取最新源码..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    warn "已存在安装目录，正在更新..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 "$REPO" "$INSTALL_DIR"
fi

# ── 创建虚拟环境 & 安装依赖 ────────────────────────────
info "创建 Python 虚拟环境..."
$PYTHON -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"

info "安装 Python 依赖..."
pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/server/requirements.txt" -q
deactivate

# ── 创建数据目录 ──────────────────────────────────────
DATA_DIR="/var/lib/netmonitor"
LOG_DIR="/var/log/netmonitor"
mkdir -p "$DATA_DIR" "$LOG_DIR"

# ── 写入 systemd service ──────────────────────────────
info "创建 systemd 服务..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=NetMonitor Server — 家用网络监控服务端
After=network.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}/server
Environment="NM_DB_PATH=${DATA_DIR}/netmonitor.db"
Environment="NM_STATIC_PATH=${INSTALL_DIR}/server/static"
ExecStart=${INSTALL_DIR}/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port ${PORT} --log-level info
Restart=on-failure
RestartSec=5
StandardOutput=append:${LOG_DIR}/server.log
StandardError=append:${LOG_DIR}/server.log

[Install]
WantedBy=multi-user.target
EOF

# ── 启动服务 ──────────────────────────────────────────
info "启用并启动服务..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "============================================================"
    echo -e "   ${GREEN}✅ 安装成功！NetMonitor Server 正在运行${NC}"
    echo "============================================================"
    echo ""
    # 获取本机 IP
    LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") print $(i+1)}' | head -1)
    if [[ -n "$LAN_IP" ]]; then
        echo "  🌐 监控面板地址：http://${LAN_IP}:${PORT}"
    fi
    echo "  🌐 本机访问地址：http://localhost:${PORT}"
    echo ""
    echo "  常用命令："
    echo "    查看状态：sudo systemctl status $SERVICE_NAME"
    echo "    查看日志：sudo tail -f ${LOG_DIR}/server.log"
    echo "    停止服务：sudo systemctl stop $SERVICE_NAME"
    echo "    重启服务：sudo systemctl restart $SERVICE_NAME"
    echo ""
else
    error "服务启动失败，请查看日志：sudo journalctl -u $SERVICE_NAME -n 50"
fi
