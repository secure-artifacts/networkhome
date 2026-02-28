"""
FastAPI 主服务入口 - WebSocket 管理 + 所有 API 路由
"""
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Body, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(__file__))
import database as db
from scheduler import start_scheduler, stop_scheduler
from discovery import run_broadcaster

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# WebSocket 连接管理器
# ──────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.add(websocket)
        logger.info("WS client connected, total=%d", len(self.active))

    def disconnect(self, websocket: WebSocket):
        self.active.discard(websocket)
        logger.info("WS client disconnected, total=%d", len(self.active))

    async def broadcast(self, data: dict):
        if not self.active:
            return
        message = json.dumps(data, ensure_ascii=False)
        dead = set()
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self.active -= dead


manager = ConnectionManager()

# 内存缓存：保存最新一条速度数据，供 WS 广播
latest_speeds: Dict[str, dict] = {}

# ──────────────────────────────────────────────
# 应用生命周期
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    start_scheduler()
    # 启动 UDP 广播（局域网自动发现）
    broadcast_task = asyncio.create_task(run_broadcaster(http_port=8866))
    logger.info("Server ready")
    yield
    broadcast_task.cancel()
    stop_scheduler()
    logger.info("Server shutting down")


app = FastAPI(title="NetMonitor", lifespan=lifespan)

# 挂载静态文件
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ──────────────────────────────────────────────
# 主页面
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/device/{device_id}", response_class=HTMLResponse)
async def device_page(device_id: str):
    return FileResponse(os.path.join(STATIC_DIR, "device.html"))


# ──────────────────────────────────────────────
# 设备 API
# ──────────────────────────────────────────────
@app.post("/api/devices/register")
async def register_device(request: Request, body: dict = Body(...)):
    """客户端 Agent 注册/更新设备信息"""
    device_id = body.get("device_id", "")
    name = body.get("name", "未知设备")
    platform = body.get("platform", "unknown")
    ip = request.client.host if request.client else "0.0.0.0"

    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")

    await db.upsert_device(device_id, name, platform, ip)
    logger.info("Device registered: %s (%s, %s)", name, platform, ip)
    return {"status": "ok", "device_id": device_id}


@app.get("/api/devices")
async def list_devices():
    """获取所有设备列表（含在线状态）"""
    devices = await db.get_all_devices()
    now = datetime.now(timezone.utc).timestamp()
    for d in devices:
        d["online"] = d.get("last_seen", 0) > now - 10  # 10秒内有上报视为在线
        # 附带最新速度数据
        d["latest"] = latest_speeds.get(d["id"], {"upload_bps": 0, "download_bps": 0})
    return devices


@app.get("/api/devices/{device_id}")
async def get_device(device_id: str):
    device = await db.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    now = datetime.now(timezone.utc).timestamp()
    device["online"] = device.get("last_seen", 0) > now - 10
    device["latest"] = latest_speeds.get(device_id, {"upload_bps": 0, "download_bps": 0})
    return device


# ──────────────────────────────────────────────
# 速度上报 API
# ──────────────────────────────────────────────
@app.post("/api/speed")
async def report_speed(request: Request, body: dict = Body(...)):
    """客户端每秒调用一次，上报实时速度"""
    device_id = body.get("device_id", "")
    upload_bps = float(body.get("upload_bps", 0))
    download_bps = float(body.get("download_bps", 0))
    timestamp = body.get("timestamp") or datetime.now(timezone.utc).timestamp()
    ip = request.client.host if request.client else "0.0.0.0"

    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")

    # 更新设备在线时间
    await db.update_device_seen(device_id, ip)

    # 存入数据库
    await db.insert_speed_log(device_id, float(timestamp), upload_bps, download_bps)

    # 更新内存缓存
    latest_speeds[device_id] = {
        "upload_bps": upload_bps,
        "download_bps": download_bps,
        "timestamp": timestamp
    }

    # WebSocket 广播
    await manager.broadcast({
        "type": "speed",
        "device_id": device_id,
        "upload_bps": upload_bps,
        "download_bps": download_bps,
        "timestamp": timestamp
    })

    return {"status": "ok"}


# ──────────────────────────────────────────────
# 统计 API（历史数据）
# ──────────────────────────────────────────────
@app.get("/api/stats/{device_id}")
async def get_stats(
    device_id: str,
    period: str = "day",
    from_ts: Optional[float] = Query(None),
    to_ts: Optional[float] = Query(None)
):
    """
    返回设备的历史统计数据
    period: day=最近24小时, week=最近7天, month=最近30天
    或者自定义 from_ts / to_ts (Unix 时间戳)
    """
    now = datetime.now(timezone.utc)
    if from_ts is not None:
        since = from_ts
        until = to_ts if to_ts else now.timestamp()
    elif period == "week":
        since = (now - timedelta(days=7)).timestamp()
        until = None
    elif period == "month":
        since = (now - timedelta(days=30)).timestamp()
        until = None
    else:  # day
        since = (now - timedelta(hours=24)).timestamp()
        until = None

    rows = await db.get_hourly_stats(device_id, since, until)
    total_up   = sum(r["upload_bytes"]   for r in rows)
    total_down = sum(r["download_bytes"] for r in rows)
    return {
        "device_id": device_id,
        "period": period,
        "total_upload_bytes":   total_up,
        "total_download_bytes": total_down,
        "hourly": rows
    }


@app.get("/api/weekly")
async def get_weekly_heatmap(weeks: int = 4):
    """全设备合计 7×24 热力图数据（迄迄 N 周的周平均）"""
    data = await db.get_weekly_heatmap(weeks)
    return {"weeks": weeks, "rows": data}


@app.get("/api/weekly/{device_id}")
async def get_device_weekly(device_id: str, weeks: int = 4):
    """单设备 7×24 热力图"""
    data = await db.get_device_weekly_heatmap(device_id, weeks)
    return {"device_id": device_id, "weeks": weeks, "rows": data}


@app.get("/api/realtime/{device_id}")
async def get_realtime(device_id: str, seconds: int = 300):
    """获取某设备最近N秒的实时速度记录（用于图表）"""
    rows = await db.get_recent_speed(device_id, seconds)
    return {"device_id": device_id, "data": rows}


@app.get("/api/peaks/{device_id}")
async def get_peaks(device_id: str, period: str = "week"):
    """
    返回高峰时段分析（按小时分组，计算平均/峰值流量）
    period: day / week / month
    """
    now = datetime.now(timezone.utc)
    if period == "month":
        since = (now - timedelta(days=30)).timestamp()
    elif period == "week":
        since = (now - timedelta(days=7)).timestamp()
    else:
        since = (now - timedelta(hours=24)).timestamp()

    rows = await db.get_hourly_stats(device_id, since)

    # 按小时（0-23）聚合
    hour_buckets: Dict[int, dict] = {h: {"upload_bytes": 0, "download_bytes": 0, "count": 0, "peak_dl": 0, "peak_ul": 0} for h in range(24)}
    for r in rows:
        dt = datetime.fromtimestamp(r["hour_start"], tz=timezone.utc)
        h = dt.hour
        hour_buckets[h]["upload_bytes"] += r["upload_bytes"]
        hour_buckets[h]["download_bytes"] += r["download_bytes"]
        hour_buckets[h]["count"] += 1
        hour_buckets[h]["peak_dl"] = max(hour_buckets[h]["peak_dl"], r["peak_download_bps"])
        hour_buckets[h]["peak_ul"] = max(hour_buckets[h]["peak_ul"], r["peak_upload_bps"])

    result = []
    for h in range(24):
        b = hour_buckets[h]
        cnt = b["count"] or 1
        result.append({
            "hour": h,
            "avg_upload_bytes": b["upload_bytes"] / cnt,
            "avg_download_bytes": b["download_bytes"] / cnt,
            "peak_upload_bps": b["peak_ul"],
            "peak_download_bps": b["peak_dl"],
        })
    return {"device_id": device_id, "period": period, "peaks": result}


# ──────────────────────────────────────────────
# WebSocket 端点
# ──────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # 发送当前所有设备最新状态
        devices = await db.get_all_devices()
        now = datetime.now(timezone.utc).timestamp()
        for d in devices:
            d["online"] = d.get("last_seen", 0) > now - 10
            d["latest"] = latest_speeds.get(d["id"], {"upload_bps": 0, "download_bps": 0})
        await websocket.send_text(json.dumps({"type": "init", "devices": devices}))

        # 保持连接，等待断开
        while True:
            await asyncio.sleep(5)
            # 每5秒发送心跳 + 在线状态更新
            now = datetime.now(timezone.utc).timestamp()
            online_map = {
                d_id: v.get("timestamp", 0) > now - 10
                for d_id, v in latest_speeds.items()
            }
            await websocket.send_text(json.dumps({"type": "heartbeat", "online": online_map}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WS error: %s", e)
        manager.disconnect(websocket)


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8866,
        reload=False,
        log_level="info"
    )
