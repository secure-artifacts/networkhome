#!/bin/bash
# NetMonitor 客户端安装脚本 (macOS/Linux)

set -e
echo "========================================"
echo "  NetMonitor 客户端安装程序 (macOS)"
echo "========================================"
echo

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装："
    echo "  macOS: brew install python3"
    exit 1
fi

echo "[1/2] 安装依赖..."
python3 -m pip install -r agent/requirements.txt

echo
echo "[2/2] 创建启动脚本..."
cat > start_agent.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
python3 agent/agent.py
EOF
chmod +x start_agent.sh

echo
echo "========================================"
echo "  安装完成！"
echo "========================================"
echo
echo "启动客户端：bash start_agent.sh"
echo "首次运行需要输入服务器地址和本机名称"
echo
