"""
网络监控客户端 Agent - 采集本机网速，每秒上报到服务器
支持 Windows 和 macOS
特性：UDP 广播自动发现服务器，无需手动输入 IP
"""
import json
import os
import platform
import socket
import sys
import time
import uuid
import logging
import threading
import requests
import psutil

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
BROADCAST_PORT = 8867
DISCOVERY_TIMEOUT = 6  # 秒


# ─── UDP 自动发现 ──────────────────────────────────────
def discover_server() -> str | None:
    """
    监听 UDP 广播，自动发现服务器地址。
    返回 "http://IP:PORT" 或 None（超时未发现）
    """
    print(f"正在局域网内搜索服务器（等待 {DISCOVERY_TIMEOUT} 秒）...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(DISCOVERY_TIMEOUT)
    try:
        sock.bind(("", BROADCAST_PORT))
        data, addr = sock.recvfrom(1024)
        info = json.loads(data.decode())
        if info.get("service") == "netmonitor":
            server_ip = addr[0]
            server_port = info.get("port", 8866)
            url = f"http://{server_ip}:{server_port}"
            print(f"✅ 自动发现服务器：{url}")
            return url
    except socket.timeout:
        print("未找到服务器广播，切换到手动输入...")
        return None
    except Exception as e:
        logger.warning("发现失败: %s", e)
        return None
    finally:
        sock.close()


def load_or_create_config() -> dict:
    """加载配置文件，首次运行时尝试自动发现服务器"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        if "device_id" not in config:
            config["device_id"] = str(uuid.uuid4())
            save_config(config)
        print(f"已加载配置：{config['device_name']} → {config['server']}")
        return config

    print("=" * 50)
    print("  NetMonitor Agent - 首次配置")
    print("=" * 50)

    # 先尝试自动发现
    server = discover_server()

    if not server:
        # 自动发现失败，手动输入
        server = input("请手动输入服务器地址（例：http://192.168.1.100:8866）: ").strip()
        if not server.startswith("http"):
            server = "http://" + server
        server = server.rstrip("/")

    name = input(f"本机名称（直接回车使用 {socket.gethostname()}）: ").strip()
    if not name:
        name = socket.gethostname()

    config = {
        "server": server,
        "device_id": str(uuid.uuid4()),
        "device_name": name,
        "report_interval": 1,
    }
    save_config(config)
    print(f"\n✅ 配置已保存到 {CONFIG_FILE}")
    return config


def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_network_speed(prev_counters, interval: float):
    curr = psutil.net_io_counters(pernic=False)
    if prev_counters is None:
        return 0.0, 0.0, curr
    bytes_sent = curr.bytes_sent - prev_counters.bytes_sent
    bytes_recv = curr.bytes_recv - prev_counters.bytes_recv
    upload_bps   = max(0, bytes_sent * 8 / interval)
    download_bps = max(0, bytes_recv * 8 / interval)
    return upload_bps, download_bps, curr


def register_device(config: dict) -> bool:
    url = f"{config['server']}/api/devices/register"
    payload = {
        "device_id": config["device_id"],
        "name": config["device_name"],
        "platform": platform.system().lower()
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        logger.info("设备注册成功: %s", config["device_name"])
        return True
    except requests.exceptions.ConnectionError:
        logger.error("无法连接到服务器 %s", config["server"])
        return False
    except Exception as e:
        logger.error("注册失败: %s", e)
        return False


def report_speed(config: dict, upload_bps: float, download_bps: float) -> bool:
    url = f"{config['server']}/api/speed"
    payload = {
        "device_id": config["device_id"],
        "upload_bps": upload_bps,
        "download_bps": download_bps,
        "timestamp": time.time()
    }
    try:
        resp = requests.post(url, json=payload, timeout=3)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning("上报失败: %s", e)
        return False


def format_speed(bps: float) -> str:
    if bps >= 1_000_000:
        return f"{bps/1_000_000:.1f} Mbps"
    elif bps >= 1_000:
        return f"{bps/1_000:.1f} Kbps"
    return f"{bps:.0f} bps"


def main():
    config = load_or_create_config()
    logger.info("设备 ID: %s", config["device_id"])

    retry = 0
    while not register_device(config):
        retry += 1
        wait = min(30, 5 * retry)
        logger.info("将在 %d 秒后重试...", wait)
        time.sleep(wait)

    interval = config.get("report_interval", 1)
    prev_counters = psutil.net_io_counters(pernic=False)
    last_time = time.time()
    consecutive_failures = 0

    logger.info("开始监控 (Ctrl+C 停止)")
    try:
        while True:
            time.sleep(interval)
            now = time.time()
            elapsed = now - last_time
            last_time = now

            upload_bps, download_bps, prev_counters = get_network_speed(prev_counters, elapsed)
            success = report_speed(config, upload_bps, download_bps)

            if success:
                consecutive_failures = 0
                sys.stdout.write(
                    f"\r↑ {format_speed(upload_bps):>12}  ↓ {format_speed(download_bps):>12}    "
                )
                sys.stdout.flush()
            else:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    logger.warning("连续5次上报失败，尝试重新注册...")
                    register_device(config)
                    consecutive_failures = 0
    except KeyboardInterrupt:
        print("\n监控已停止")


if __name__ == "__main__":
    main()
