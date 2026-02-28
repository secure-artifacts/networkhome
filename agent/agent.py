"""
NetMonitor Agent — 系统托盘版 v3 (Windows / macOS)

功能:
  - 系统托盘图标，无控制台窗口
  - 后台持续 UDP 广播扫描，自动找到服务器后立即连接
  - 30 秒仍未找到 → 弹输入框手动填写服务器地址
  - 服务器失联后自动重新扫描，重新连接
  - 右键菜单：修改设备名称 / 修改服务器 / 开机自启 / 退出
  - 首次运行弹框设备名，默认 = 电脑用户名
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
from PIL import Image, ImageDraw

# ── 平台 ──────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# ── 路径 ─────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE    = os.path.join(BASE_DIR, "agent.log")

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)
logger = logging.getLogger(__name__)

BROADCAST_PORT = 8867


# ══════════════════════════════════════════════════════
# 托盘图标生成
# ══════════════════════════════════════════════════════
def _make_icon(color):
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = 6
    draw.ellipse([m, m, size - m, size - m], fill=color)
    draw.text((22, 18), "N", fill="white")
    return img

ICON_GREEN  = lambda: _make_icon((52, 211, 153))   # 已连接
ICON_YELLOW = lambda: _make_icon((251, 191, 36))    # 搜索/连接中
ICON_RED    = lambda: _make_icon((248, 113, 113))   # 断开


# ══════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════
# 轻量 tkinter 对话框（可从任意线程调用）
# ══════════════════════════════════════════════════════
def _tk_ask(title: str, prompt: str, initial: str = "") -> str | None:
    """在新线程里弹 askstring 对话框，返回用户输入（None=取消）"""
    import tkinter as tk
    from tkinter import simpledialog
    result = [None]
    done   = threading.Event()

    def _show():
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        val = simpledialog.askstring(title, prompt, parent=root, initialvalue=initial)
        result[0] = val.strip() if val and val.strip() else None
        root.destroy()
        done.set()

    threading.Thread(target=_show, daemon=True).start()
    done.wait(timeout=300)
    return result[0]


# ══════════════════════════════════════════════════════
# 开机自启
# ══════════════════════════════════════════════════════
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
            winreg.QueryValueEx(k, "NetMonitor-Agent")
            winreg.CloseKey(k)
            return True
        except Exception:
            return False
    elif IS_MAC:
        return os.path.exists(os.path.expanduser(
            "~/Library/LaunchAgents/com.netmonitor.agent.plist"))
    return False

def set_startup(enable: bool):
    if IS_WIN:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(k, "NetMonitor-Agent", 0, winreg.REG_SZ, _exe_path())
        else:
            try: winreg.DeleteValue(k, "NetMonitor-Agent")
            except FileNotFoundError: pass
        winreg.CloseKey(k)
    elif IS_MAC:
        plist_path = os.path.expanduser(
            "~/Library/LaunchAgents/com.netmonitor.agent.plist")
        if enable:
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
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
    logger.info("开机自启: %s", "启用" if enable else "禁用")


# ══════════════════════════════════════════════════════
# 持续 UDP 发现线程
# ══════════════════════════════════════════════════════
class DiscoveryLoop:
    """
    后台持续扫描局域网 UDP 广播，找到服务器就调用 on_found(url)。
    若 30 秒内未发现且尚未配置过服务器，弹出手动输入框。
    此后每 10 秒继续尝试，以应对服务器重启或网络切换。
    """

    FIRST_TIMEOUT  = 30   # 首次等待秒数（未配置时）
    RESCAN_INTERVAL = 10  # 失联后重扫间隔

    def __init__(self, on_found, has_saved_server: bool):
        self._on_found        = on_found
        self._has_saved       = has_saved_server
        self._stop            = threading.Event()
        self._found           = threading.Event()
        self._elapsed         = 0

    def start(self):
        t = threading.Thread(target=self._run, daemon=True, name="discovery")
        t.start()

    def mark_found(self):
        self._found.set()

    def mark_lost(self):
        """服务器失联，重新开始扫描"""
        self._found.clear()
        logger.info("服务器失联，重启扫描...")

    def stop(self):
        self._stop.set()

    # ── 内部 ─────────────────────────────────────────
    def _try_once(self, timeout=6) -> str | None:
        """监听一次 UDP 广播，timeout 秒内未收到返回 None"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)
            sock.bind(("", BROADCAST_PORT))
            data, addr = sock.recvfrom(1024)
            info = json.loads(data.decode())
            if info.get("service") == "netmonitor":
                return f"http://{addr[0]}:{info.get('port', 8866)}"
        except socket.timeout:
            pass
        except Exception as e:
            logger.debug("发现异常: %s", e)
        finally:
            try: sock.close()
            except: pass
        return None

    def _run(self):
        wait_start = time.time()
        prompted   = False

        while not self._stop.is_set():
            # 已找到 → 暂停，等待失联信号
            if self._found.is_set():
                self._stop.wait(timeout=2)
                continue

            url = self._try_once(timeout=5)
            if url:
                logger.info("发现服务器: %s", url)
                self._on_found(url)
                self.mark_found()
                wait_start = time.time()
                prompted   = False
                continue

            # 没找到 — 计时
            elapsed = time.time() - wait_start
            logger.debug("扫描中... %.0fs", elapsed)

            # 超过 30 秒且还没有保存过服务器 → 弹输入框（只弹一次）
            if not prompted and not self._has_saved and elapsed >= self.FIRST_TIMEOUT:
                prompted = True
                logger.info("30 秒未发现服务器，弹手动输入框")
                manual = _tk_ask(
                    "找不到服务器",
                    "局域网内未发现 NetMonitor 服务器。\n"
                    "请手动输入服务器地址（如 http://192.168.1.5:8866）：",
                    initial=""
                )
                if manual:
                    self._has_saved = True
                    self._on_found(manual)
                    self.mark_found()
                    wait_start = time.time()
                else:
                    # 用户取消 → 继续扫描
                    wait_start = time.time()

            # 短暂等待再重试
            self._stop.wait(timeout=self.RESCAN_INTERVAL)


# ══════════════════════════════════════════════════════
# Agent 主体
# ══════════════════════════════════════════════════════
class NetMonitorAgent:
    def __init__(self):
        self.cfg        = load_config()
        self.status     = "正在搜索服务器..."
        self.up_bps     = 0.0
        self.down_bps   = 0.0
        self.running    = True
        self.registered = False
        self.tray_icon  = None
        self._lock      = threading.Lock()
        self._discovery: DiscoveryLoop | None = None

    # ── 发现回调 ─────────────────────────────────────
    def _on_server_found(self, url: str):
        """当 DiscoveryLoop 找到服务器时调用（可来自任意线程）"""
        if url != self.cfg.get("server"):
            logger.info("服务器地址更新: %s → %s", self.cfg.get("server"), url)
            self.cfg["server"] = url
            save_config(self.cfg)
        self.registered = False   # 触发重新注册

    # ── 首次配置（只设备名，服务器由发现线程搞定）────
    def _ensure_device_name(self):
        if not self.cfg.get("device_name"):
            default = socket.gethostname()
            name = _tk_ask(
                "设备名称",
                f"设置本设备的名称（留空使用「{default}」）：",
                initial=default
            ) or default
            self.cfg["device_name"] = name
            self.cfg.setdefault("device_id", str(uuid.uuid4()))
            save_config(self.cfg)
            logger.info("设备名称: %s", name)

    # ── HTTP 注册 & 上报 ─────────────────────────────
    def _register(self) -> bool:
        if not self.cfg.get("server"):
            return False
        try:
            r = requests.post(
                f"{self.cfg['server']}/api/devices/register",
                json={
                    "device_id": self.cfg["device_id"],
                    "name":      self.cfg["device_name"],
                    "platform":  platform.system().lower(),
                },
                timeout=5
            )
            r.raise_for_status()
            self.registered = True
            return True
        except Exception as e:
            logger.warning("注册失败: %s", e)
            return False

    def _report(self) -> bool:
        try:
            r = requests.post(
                f"{self.cfg['server']}/api/speed",
                json={
                    "device_id":    self.cfg["device_id"],
                    "upload_bps":   self.up_bps,
                    "download_bps": self.down_bps,
                    "timestamp":    time.time(),
                },
                timeout=3
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.debug("上报失败: %s", e)
            return False

    # ── 网速采集主循环 ───────────────────────────────
    def _monitor_loop(self):
        prev   = psutil.net_io_counters(pernic=False)
        last_t = time.time()
        fails  = 0

        while self.running:
            interval = self.cfg.get("report_interval", 1)
            time.sleep(interval)
            if not self.running:
                break

            now     = time.time()
            elapsed = max(now - last_t, 0.001)
            last_t  = now
            curr    = psutil.net_io_counters(pernic=False)

            with self._lock:
                self.up_bps   = max(0, (curr.bytes_sent - prev.bytes_sent) * 8 / elapsed)
                self.down_bps = max(0, (curr.bytes_recv - prev.bytes_recv) * 8 / elapsed)
            prev = curr

            # 尚未有服务器地址
            if not self.cfg.get("server"):
                self._update_tray("正在搜索服务器...", ICON_YELLOW)
                continue

            # 未注册
            if not self.registered:
                self._update_tray("正在连接服务器...", ICON_YELLOW)
                if self._register():
                    self._update_tray("已连接", ICON_GREEN)
                    fails = 0
                else:
                    fails += 1
                    if fails >= 3:
                        self.registered = False
                        if self._discovery:
                            self._discovery.mark_lost()
                            self.cfg["server"] = ""
                        self._update_tray("连接失败，重新搜索...", ICON_RED)
                        fails = 0
                continue

            # 正常上报
            if self._report():
                fails = 0
                self._update_tray(
                    f"已连接 | ↑{self._fmt(self.up_bps)} ↓{self._fmt(self.down_bps)}",
                    ICON_GREEN
                )
            else:
                fails += 1
                if fails >= 5:
                    self.registered = False
                    if self._discovery:
                        self._discovery.mark_lost()
                    self._update_tray("服务器失联，重新搜索...", ICON_RED)
                    fails = 0

    def _update_tray(self, text: str, icon_fn):
        self.status = text
        if self.tray_icon:
            try:
                self.tray_icon.icon  = icon_fn()
                self.tray_icon.title = f"NetMonitor — {text}"
            except Exception:
                pass

    @staticmethod
    def _fmt(bps: float) -> str:
        if bps >= 1e6: return f"{bps/1e6:.1f}M"
        if bps >= 1e3: return f"{bps/1e3:.0f}K"
        return f"{int(bps)}bps"

    # ── 托盘菜单 ─────────────────────────────────────
    def _on_change_name(self, icon, item):
        val = _tk_ask("修改设备名称", "新的设备名称：",
                      self.cfg.get("device_name", socket.gethostname()))
        if val:
            self.cfg["device_name"] = val
            save_config(self.cfg)
            self.registered = False

    def _on_change_server(self, icon, item):
        val = _tk_ask("修改服务器地址", "服务器地址（如 http://192.168.1.5:8866）：",
                      self.cfg.get("server", ""))
        if val:
            self.cfg["server"] = val.rstrip("/")
            save_config(self.cfg)
            self.registered = False
            if self._discovery:
                self._discovery.mark_found()  # 暂停扫描

    def _on_startup_toggle(self, icon, item):
        set_startup(not is_startup_enabled())
        icon.update_menu()

    def _on_quit(self, icon, item):
        self.running = False
        if self._discovery:
            self._discovery.stop()
        icon.stop()

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(lambda _: self.status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("修改设备名称...", self._on_change_name),
            pystray.MenuItem("修改服务器地址...", self._on_change_server),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "开机自启",
                self._on_startup_toggle,
                checked=lambda _: is_startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出 NetMonitor", self._on_quit),
        )

    # ── 启动 ─────────────────────────────────────────
    def run(self):
        # 1. 确保有设备名
        self._ensure_device_name()

        # 2. 启动持续发现
        self._discovery = DiscoveryLoop(
            on_found=self._on_server_found,
            has_saved_server=bool(self.cfg.get("server"))
        )
        # 如果已有保存的服务器，先用它，同时后台继续监听（以便服务器换 IP 后自动更新）
        if self.cfg.get("server"):
            self._discovery.mark_found()   # 不立即弹框
        self._discovery.start()

        # 3. 启动网速采集
        threading.Thread(target=self._monitor_loop, daemon=True, name="monitor").start()

        # 4. 系统托盘（主线程阻塞）
        self.tray_icon = pystray.Icon(
            name="NetMonitor",
            icon=ICON_YELLOW(),
            title="NetMonitor — 正在搜索服务器...",
            menu=self._build_menu(),
        )
        self.tray_icon.run()


# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    NetMonitorAgent().run()
