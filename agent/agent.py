"""
NetMonitor Agent — 系统托盘版 (Windows / macOS)

功能:
  - 系统托盘图标，无控制台窗口
  - 图标颜色: 绿=已连接, 黄=连接中, 红=失败
  - 右键菜单: 状态 / 修改设备名称 / 开机自启 / 退出
  - 首次运行弹小对话框设置设备名称（默认=电脑用户名）
  - 后台线程采集网速并上报，支持 UDP 自动发现服务器
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

import psutil
import requests
import pystray
from PIL import Image, ImageDraw, ImageFont

# ── 平台判断 ──────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# ── 路径 ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE    = os.path.join(BASE_DIR, "agent.log")

# ── 日志（写文件，不弹控制台）────────────────────────
logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)
logger = logging.getLogger(__name__)

BROADCAST_PORT   = 8867
DISCOVERY_TIMEOUT = 6


# ══════════════════════════════════════════════════════
# 图标生成
# ══════════════════════════════════════════════════════
def make_icon(color=(52, 211, 153)):
    """生成 64×64 圆形托盘图标，颜色表示连接状态"""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = 6
    draw.ellipse([m, m, size-m, size-m], fill=color)
    # 画 "N" 字
    draw.text((22, 18), "N", fill="white")
    return img

ICON_GREEN  = lambda: make_icon((52, 211, 153))   # 已连接
ICON_YELLOW = lambda: make_icon((251, 191, 36))    # 连接中
ICON_RED    = lambda: make_icon((248, 113, 113))   # 断开


# ══════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════
# UDP 自动发现
# ══════════════════════════════════════════════════════
def discover_server():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(DISCOVERY_TIMEOUT)
        sock.bind(("", BROADCAST_PORT))
        data, addr = sock.recvfrom(1024)
        info = json.loads(data.decode())
        if info.get("service") == "netmonitor":
            url = f"http://{addr[0]}:{info.get('port', 8866)}"
            logger.info("自动发现服务器: %s", url)
            return url
    except socket.timeout:
        logger.info("未发现服务器广播")
    except Exception as e:
        logger.warning("发现失败: %s", e)
    finally:
        try: sock.close()
        except: pass
    return None


# ══════════════════════════════════════════════════════
# 小对话框（tkinter，不显示主窗口）
# ══════════════════════════════════════════════════════
def ask_string(title, prompt, initial=""):
    """在任意线程里弹出输入框，返回输入字符串"""
    import tkinter as tk
    from tkinter import simpledialog
    result = [initial]
    done   = threading.Event()

    def _show():
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        val = simpledialog.askstring(title, prompt, parent=root, initialvalue=initial)
        if val and val.strip():
            result[0] = val.strip()
        root.destroy()
        done.set()

    threading.Thread(target=_show, daemon=True).start()
    done.wait(timeout=120)
    return result[0]

def show_input_dialog_server(initial=""):
    return ask_string("服务器地址", "输入服务器地址（如 http://192.168.1.5:8866）：", initial)

def show_input_dialog_name(initial=""):
    return ask_string("设备名称", "输入本设备的名称：", initial)


# ══════════════════════════════════════════════════════
# 开机自启
# ══════════════════════════════════════════════════════
def get_exe_path():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'

def is_startup_enabled():
    if IS_WIN:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                0, winreg.KEY_READ)
            winreg.QueryValueEx(key, "NetMonitor-Agent")
            winreg.CloseKey(key)
            return True
        except Exception:
            return False
    elif IS_MAC:
        plist = os.path.expanduser("~/Library/LaunchAgents/com.netmonitor.agent.plist")
        return os.path.exists(plist)
    return False

def set_startup(enable: bool):
    if IS_WIN:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, "NetMonitor-Agent", 0, winreg.REG_SZ, get_exe_path())
        else:
            try: winreg.DeleteValue(key, "NetMonitor-Agent")
            except FileNotFoundError: pass
        winreg.CloseKey(key)
    elif IS_MAC:
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.netmonitor.agent.plist")
        if enable:
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.netmonitor.agent</string>
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
    logger.info("开机自启: %s", "已启用" if enable else "已禁用")


# ══════════════════════════════════════════════════════
# Agent 主逻辑
# ══════════════════════════════════════════════════════
class NetMonitorAgent:
    def __init__(self):
        self.cfg           = load_config()
        self.status        = "连接中..."
        self.up_bps        = 0.0
        self.down_bps      = 0.0
        self.running       = True
        self.registered    = False
        self.tray_icon     = None
        self._lock         = threading.Lock()

    # ── 首次配置向导 ─────────────────────────────────
    def first_run_setup(self):
        """首次运行：询问服务器地址和设备名称"""
        # 尝试自动发现
        server = discover_server()
        if not server:
            server = self.cfg.get("server", "")
            server = show_input_dialog_server(server or "http://192.168.1.x:8866")

        # 设备名称（默认 = 电脑用户名）
        default_name = socket.gethostname()
        name = self.cfg.get("device_name", "")
        if not name:
            name = show_input_dialog_name(default_name) or default_name

        self.cfg.update({
            "server":      server.rstrip("/"),
            "device_id":   self.cfg.get("device_id", str(uuid.uuid4())),
            "device_name": name,
            "report_interval": 1,
        })
        save_config(self.cfg)

    def is_configured(self):
        return bool(self.cfg.get("server") and self.cfg.get("device_name"))

    # ── 注册 & 上报 ──────────────────────────────────
    def register(self):
        url = f"{self.cfg['server']}/api/devices/register"
        payload = {
            "device_id": self.cfg["device_id"],
            "name":      self.cfg["device_name"],
            "platform":  platform.system().lower(),
        }
        try:
            resp = requests.post(url, json=payload, timeout=5)
            resp.raise_for_status()
            self.registered = True
            logger.info("注册成功: %s", self.cfg["device_name"])
            return True
        except Exception as e:
            logger.warning("注册失败: %s", e)
            return False

    def report_speed(self):
        url = f"{self.cfg['server']}/api/speed"
        payload = {
            "device_id":    self.cfg["device_id"],
            "upload_bps":   self.up_bps,
            "download_bps": self.down_bps,
            "timestamp":    time.time(),
        }
        try:
            resp = requests.post(url, json=payload, timeout=3)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.debug("上报失败: %s", e)
            return False

    # ── 网速采集线程 ─────────────────────────────────
    def monitor_loop(self):
        prev    = psutil.net_io_counters(pernic=False)
        last_t  = time.time()
        fails   = 0

        while self.running:
            interval = self.cfg.get("report_interval", 1)
            time.sleep(interval)
            if not self.running: break

            now     = time.time()
            elapsed = now - last_t
            last_t  = now
            curr    = psutil.net_io_counters(pernic=False)

            with self._lock:
                self.up_bps   = max(0, (curr.bytes_sent - prev.bytes_sent) * 8 / elapsed)
                self.down_bps = max(0, (curr.bytes_recv - prev.bytes_recv) * 8 / elapsed)
            prev = curr

            if not self.registered:
                if self.register():
                    self._set_status("已连接", ICON_GREEN)
                else:
                    self._set_status("连接失败，重试中...", ICON_RED)
                    continue

            if self.report_speed():
                fails = 0
                self._set_status(
                    f"已连接 | ↑{self._fmt(self.up_bps)} ↓{self._fmt(self.down_bps)}",
                    ICON_GREEN
                )
            else:
                fails += 1
                if fails >= 5:
                    self.registered = False
                    fails = 0
                    self._set_status("连接断开，重连中...", ICON_YELLOW)

    def _set_status(self, text, icon_fn):
        self.status = text
        if self.tray_icon:
            try:
                self.tray_icon.icon    = icon_fn()
                self.tray_icon.title   = f"NetMonitor — {text}"
            except Exception:
                pass

    @staticmethod
    def _fmt(bps):
        if bps >= 1e6: return f"{bps/1e6:.1f}Mbps"
        if bps >= 1e3: return f"{bps/1e3:.0f}Kbps"
        return f"{bps:.0f}bps"

    # ── 托盘菜单 ─────────────────────────────────────
    def _menu_status(self):
        return pystray.MenuItem(lambda item: self.status, None, enabled=False)

    def _menu_change_name(self, icon, item):
        new_name = show_input_dialog_name(self.cfg.get("device_name", ""))
        if new_name and new_name != self.cfg.get("device_name"):
            self.cfg["device_name"] = new_name
            save_config(self.cfg)
            self.registered = False  # 触发重新注册
            logger.info("设备名称改为: %s", new_name)

    def _menu_change_server(self, icon, item):
        new_srv = show_input_dialog_server(self.cfg.get("server", ""))
        if new_srv and new_srv != self.cfg.get("server"):
            self.cfg["server"] = new_srv.rstrip("/")
            save_config(self.cfg)
            self.registered = False
            logger.info("服务器改为: %s", new_srv)

    def _menu_startup_toggle(self, icon, item):
        current = is_startup_enabled()
        set_startup(not current)
        # 更新菜单 checked 状态需刷新菜单
        icon.update_menu()

    def _menu_quit(self, icon, item):
        self.running = False
        icon.stop()

    def build_menu(self):
        return pystray.Menu(
            self._menu_status(),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("修改设备名称...", self._menu_change_name),
            pystray.MenuItem("修改服务器地址...", self._menu_change_server),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "开机自启",
                self._menu_startup_toggle,
                checked=lambda item: is_startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出 NetMonitor", self._menu_quit),
        )

    # ── 启动入口 ─────────────────────────────────────
    def run(self):
        if not self.is_configured():
            self.first_run_setup()

        # 启动网速采集线程
        t = threading.Thread(target=self.monitor_loop, daemon=True)
        t.start()

        # 创建托盘图标（主线程阻塞）
        self.tray_icon = pystray.Icon(
            name="NetMonitor",
            icon=ICON_YELLOW(),
            title="NetMonitor — 正在连接...",
            menu=self.build_menu(),
        )
        self.tray_icon.run()


# ══════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    agent = NetMonitorAgent()
    agent.run()
