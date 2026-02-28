"""
NetMonitor Server — 系统托盘版

- 后台运行 FastAPI 服务器（uvicorn，端口 8866）
- 系统托盘图标（绿=运行中，黄=启动中，红=错误）
- 右键菜单：
    · 打开监控面板（浏览器）
    · 本机地址：xxx.xxx.xxx.xxx:8866（不可点击，仅展示）
    · 复制地址（写剪贴板）
    · 开机自启（Windows 注册表）
    · 退出
"""

import os
import sys
import socket
import platform
import threading
import webbrowser
import time
import logging

import uvicorn
import pystray
from PIL import Image, ImageDraw

# ── 平台 ──────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
SERVER_PORT = 8866

# ── 用户数据目录 & 日志 ──────────────────────────────────
def _get_data_dir() -> str:
    if IS_WIN:
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif IS_MAC:
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    d = os.path.join(base, "NetMonitor", "server")
    os.makedirs(d, exist_ok=True)
    return d

DATA_DIR = _get_data_dir()
LOG_FILE = os.path.join(DATA_DIR, "server.log")
DB_FILE  = os.path.join(DATA_DIR, "netmonitor.db")

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)
logger = logging.getLogger(__name__)

# ── PyInstaller 路径适配 ──────────────────────────────────
# 打包后 static/ 在 sys._MEIPASS/static；开发时在 server/static
if getattr(sys, 'frozen', False):
    _base = sys._MEIPASS
else:
    _base = os.path.dirname(os.path.abspath(__file__))

STATIC_PATH = os.path.join(_base, "static")

# 通过环境变量告知 main.py 使用哪个 static 目录
os.environ["NM_STATIC_PATH"] = STATIC_PATH
# 告知 database.py 使用可写路径
os.environ["NM_DB_PATH"]     = DB_FILE

# 把打包内目录加入 sys.path，以便 import main / database 等
sys.path.insert(0, _base)


# ── 获取本机 LAN IP ──────────────────────────────────────
# 已知虚拟/VPN 网卡关键词（名称或描述包含这些的跳过）
_VIRTUAL_KW = {
    'loopback', 'virtual', 'vmware', 'virtualbox', 'vbox',
    'hyper-v', 'wsl', 'docker', 'zerotier', 'tailscale',
    'nordvpn', 'expressvpn', 'vpn', 'tap', 'tun',
    'vethernet', 'pseudo', 'teredo', 'isatap', '6to4',
}

def _is_virtual(iface_name: str) -> bool:
    n = iface_name.lower()
    return any(kw in n for kw in _VIRTUAL_KW)

def get_lan_ips() -> list[str]:
    """
    返回本机真实局域网 IP（过滤虚拟/VPN 网卡），
    优先顺序：192.168.x.x → 172.16-31.x.x → 10.x.x.x
    """
    buckets = {0: [], 1: [], 2: []}  # 0=192.168, 1=172, 2=10
    try:
        import psutil
        for iface, addrs in psutil.net_if_addrs().items():
            if _is_virtual(iface):
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if ip.startswith('192.168.'):
                        buckets[0].append(ip)
                    elif ip.startswith('172.') and 16 <= int(ip.split('.')[1]) <= 31:
                        buckets[1].append(ip)
                    elif ip.startswith('10.'):
                        buckets[2].append(ip)
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
            if not ip.startswith('127.'):
                return [ip]
        except Exception:
            pass

    # 返回优先级最高的那组，三组都有就按顺序合并
    result = buckets[0] or buckets[1] or buckets[2]
    return result or ['127.0.0.1']

def get_primary_url() -> str:
    ips = get_lan_ips()
    return f"http://{ips[0]}:{SERVER_PORT}"


# ── 剪贴板 ────────────────────────────────────────────────
def copy_to_clipboard(text: str):
    if IS_WIN:
        import subprocess
        subprocess.run(["clip"], input=text.encode("utf-8"), check=True)
    elif IS_MAC:
        import subprocess
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    else:
        try:
            import subprocess
            subprocess.run(["xclip", "-selection", "clipboard"],
                           input=text.encode("utf-8"), check=True)
        except Exception:
            pass


# ── 托盘图标 ──────────────────────────────────────────────
def _make_icon(color):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = 6
    draw.ellipse([m, m, size - m, size - m], fill=color)
    draw.text((18, 18), "NM", fill="white")
    return img

ICON_GREEN  = lambda: _make_icon((52, 211, 153))
ICON_YELLOW = lambda: _make_icon((251, 191, 36))
ICON_RED    = lambda: _make_icon((248, 113, 113))


# ── 开机自启 ──────────────────────────────────────────────
def _exe_path() -> str:
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'

def is_startup_enabled() -> bool:
    if IS_WIN:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ)
            winreg.QueryValueEx(k, "NetMonitor-Server")
            winreg.CloseKey(k)
            return True
        except Exception:
            return False
    elif IS_MAC:
        return os.path.exists(os.path.expanduser(
            "~/Library/LaunchAgents/com.netmonitor.server.plist"))
    return False

def set_startup(enable: bool):
    if IS_WIN:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(k, "NetMonitor-Server", 0, winreg.REG_SZ, _exe_path())
        else:
            try: winreg.DeleteValue(k, "NetMonitor-Server")
            except FileNotFoundError: pass
        winreg.CloseKey(k)
    elif IS_MAC:
        plist_path = os.path.expanduser(
            "~/Library/LaunchAgents/com.netmonitor.server.plist")
        if enable:
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.netmonitor.server</string>
  <key>ProgramArguments</key><array><string>{sys.executable}</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>"""
            os.makedirs(os.path.dirname(plist_path), exist_ok=True)
            with open(plist_path, "w") as f: f.write(plist)
            os.system(f"launchctl load '{plist_path}'")
        else:
            if os.path.exists(plist_path):
                os.system(f"launchctl unload '{plist_path}'")
                os.remove(plist_path)


# ══════════════════════════════════════════════════════════
# 服务器 Tray App
# ══════════════════════════════════════════════════════════
class ServerTray:
    def __init__(self):
        self.tray_icon  = None
        self.running    = True
        self._server_ok = False

    # ── 启动 uvicorn ──────────────────────────────────────
    def _start_server(self):
        try:
            # 延迟导入，确保环境变量已设置
            from main import app  # noqa
            logger.info("Starting uvicorn on port %d", SERVER_PORT)
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=SERVER_PORT,
                log_level="warning",   # 减少噪音
                access_log=False,
            )
        except Exception as e:
            logger.error("Server error: %s", e)
            self._server_ok = False
            if self.tray_icon:
                self.tray_icon.icon  = ICON_RED()
                self.tray_icon.title = f"NetMonitor Server — 错误: {e}"

    def _wait_and_mark_ready(self):
        """等待端口可用后更新图标"""
        for _ in range(30):
            time.sleep(1)
            try:
                s = socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=1)
                s.close()
                self._server_ok = True
                url = get_primary_url()
                if self.tray_icon:
                    self.tray_icon.icon  = ICON_GREEN()
                    self.tray_icon.title = f"NetMonitor — {url}"
                logger.info("Server ready at %s", url)
                return
            except OSError:
                pass
        logger.warning("Server did not start in time")

    # ── 菜单回调 ──────────────────────────────────────────
    def _on_open(self, icon, item):
        webbrowser.open(get_primary_url())

    def _on_copy(self, icon, item):
        url = get_primary_url()
        try:
            copy_to_clipboard(url)
            icon.title = f"NetMonitor — 已复制: {url}"
        except Exception as e:
            logger.warning("Copy failed: %s", e)

    def _on_startup_toggle(self, icon, item):
        set_startup(not is_startup_enabled())
        icon.update_menu()

    def _on_quit(self, icon, item):
        self.running = False
        icon.stop()
        # uvicorn 在 daemon 线程中，进程退出后自动停止

    # ── 菜单构建 ──────────────────────────────────────────
    def _build_menu(self):
        ips     = get_lan_ips()
        ip_line = "  ".join(f"{ip}:{SERVER_PORT}" for ip in ips)

        return pystray.Menu(
            pystray.MenuItem("📊 打开监控面板", self._on_open, default=True),
            pystray.Menu.SEPARATOR,
            # 显示地址（不可点击）
            pystray.MenuItem(
                lambda _: f"🖥  {ip_line}",
                None, enabled=False
            ),
            pystray.MenuItem("📋 复制访问地址", self._on_copy),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "开机自启",
                self._on_startup_toggle,
                checked=lambda _: is_startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出 NetMonitor Server", self._on_quit),
        )

    # ── 主入口 ────────────────────────────────────────────
    def run(self):
        # 1. 启动服务器线程
        t_server = threading.Thread(target=self._start_server, daemon=True, name="uvicorn")
        t_server.start()

        # 2. 等待就绪线程（更新图标颜色）
        t_ready = threading.Thread(target=self._wait_and_mark_ready, daemon=True, name="readywatcher")
        t_ready.start()

        # 3. 托盘（主线程阻塞）
        self.tray_icon = pystray.Icon(
            name="NetMonitor-Server",
            icon=ICON_YELLOW(),
            title="NetMonitor Server — 启动中...",
            menu=self._build_menu(),
        )
        self.tray_icon.run()


# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    ServerTray().run()
