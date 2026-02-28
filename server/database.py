"""
数据库管理模块 - 创建表结构、提供读写接口
"""
import aiosqlite
import os
import logging
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "netmonitor.db")
logger = logging.getLogger(__name__)


async def init_db():
    """初始化数据库，创建所有表"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                ip TEXT,
                last_seen REAL,
                created_at REAL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS speed_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                upload_bps REAL NOT NULL,
                download_bps REAL NOT NULL,
                FOREIGN KEY (device_id) REFERENCES devices(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_speed_logs_device_time ON speed_logs(device_id, timestamp)")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS hourly_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                hour_start REAL NOT NULL,
                upload_bytes REAL NOT NULL DEFAULT 0,
                download_bytes REAL NOT NULL DEFAULT 0,
                avg_upload_bps REAL NOT NULL DEFAULT 0,
                avg_download_bps REAL NOT NULL DEFAULT 0,
                peak_upload_bps REAL NOT NULL DEFAULT 0,
                peak_download_bps REAL NOT NULL DEFAULT 0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(device_id, hour_start),
                FOREIGN KEY (device_id) REFERENCES devices(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hourly_device_hour ON hourly_stats(device_id, hour_start)")

        await db.commit()
        logger.info("Database initialized at %s", DB_PATH)


async def upsert_device(device_id: str, name: str, platform: str, ip: str):
    now = datetime.now(timezone.utc).timestamp()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO devices (id, name, platform, ip, last_seen, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                platform=excluded.platform,
                ip=excluded.ip,
                last_seen=excluded.last_seen
        """, (device_id, name, platform, ip, now, now))
        await db.commit()


async def update_device_seen(device_id: str, ip: str):
    now = datetime.now(timezone.utc).timestamp()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE devices SET last_seen=?, ip=? WHERE id=?",
            (now, ip, device_id)
        )
        await db.commit()


async def insert_speed_log(device_id: str, timestamp: float, upload_bps: float, download_bps: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO speed_logs (device_id, timestamp, upload_bps, download_bps) VALUES (?,?,?,?)",
            (device_id, timestamp, upload_bps, download_bps)
        )
        await db.commit()


async def get_all_devices():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM devices ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_device(device_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM devices WHERE id=?", (device_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_recent_speed(device_id: str, seconds: int = 300):
    """获取最近N秒的速度记录"""
    since = datetime.now(timezone.utc).timestamp() - seconds
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT timestamp, upload_bps, download_bps
            FROM speed_logs
            WHERE device_id=? AND timestamp>=?
            ORDER BY timestamp ASC
        """, (device_id, since))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_hourly_stats(device_id: str, since_ts: float, until_ts: float | None = None):
    """获取某设备从 since_ts 开始的小时聚合数据"""
    until_ts = until_ts or (datetime.now(timezone.utc).timestamp() + 1)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT hour_start, upload_bytes, download_bytes,
                   avg_upload_bps, avg_download_bps, peak_upload_bps, peak_download_bps
            FROM hourly_stats
            WHERE device_id=? AND hour_start>=? AND hour_start<=?
            ORDER BY hour_start ASC
        """, (device_id, since_ts, until_ts))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_weekly_heatmap(weeks: int = 4):
    """全设备合计，按星期几(0=周日)+小时 聚合，返回 7×24 矩阵"""
    since = datetime.now(timezone.utc).timestamp() - weeks * 7 * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                CAST(strftime('%w', datetime(hour_start,'unixepoch')) AS INTEGER) AS dow,
                CAST(strftime('%H', datetime(hour_start,'unixepoch')) AS INTEGER) AS hr,
                AVG(upload_bytes)   AS avg_up,
                AVG(download_bytes) AS avg_down,
                MAX(upload_bytes)   AS peak_up,
                MAX(download_bytes) AS peak_down
            FROM hourly_stats
            WHERE hour_start >= ?
            GROUP BY dow, hr
        """, (since,))
        rows = await cursor.fetchall()
        # Build 7x24 matrix {dow: {hr: {up, down}}}
        matrix = {d: {h: {"avg_up": 0, "avg_down": 0} for h in range(24)} for d in range(7)}
        for r in rows:
            matrix[r["dow"]][r["hr"]] = {"avg_up": r["avg_up"] or 0, "avg_down": r["avg_down"] or 0}
        # Convert to list sorted Mon-Sun (dow 1..6,0)
        result = []
        for dow_idx in [1, 2, 3, 4, 5, 6, 0]:  # Mon-Sun
            row = {"dow": dow_idx, "hours": [matrix[dow_idx][h] for h in range(24)]}
            result.append(row)
        return result


async def get_device_weekly_heatmap(device_id: str, weeks: int = 4):
    """单设备，按星期几+小时聚合"""
    since = datetime.now(timezone.utc).timestamp() - weeks * 7 * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                CAST(strftime('%w', datetime(hour_start,'unixepoch')) AS INTEGER) AS dow,
                CAST(strftime('%H', datetime(hour_start,'unixepoch')) AS INTEGER) AS hr,
                AVG(upload_bytes)   AS avg_up,
                AVG(download_bytes) AS avg_down
            FROM hourly_stats
            WHERE device_id=? AND hour_start >= ?
            GROUP BY dow, hr
        """, (device_id, since))
        rows = await cursor.fetchall()
        matrix = {d: {h: {"avg_up": 0, "avg_down": 0} for h in range(24)} for d in range(7)}
        for r in rows:
            matrix[r["dow"]][r["hr"]] = {"avg_up": r["avg_up"] or 0, "avg_down": r["avg_down"] or 0}
        result = []
        for dow_idx in [1, 2, 3, 4, 5, 6, 0]:
            row = {"dow": dow_idx, "hours": [matrix[dow_idx][h] for h in range(24)]}
            result.append(row)
        return result


async def aggregate_hour(device_id: str, hour_start: float):
    """聚合某小时的 speed_logs 数据到 hourly_stats"""
    hour_end = hour_start + 3600
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT
                SUM(upload_bps) / 8.0 AS upload_bytes,
                SUM(download_bps) / 8.0 AS download_bytes,
                AVG(upload_bps) AS avg_up,
                AVG(download_bps) AS avg_down,
                MAX(upload_bps) AS peak_up,
                MAX(download_bps) AS peak_down,
                COUNT(*) AS cnt
            FROM speed_logs
            WHERE device_id=? AND timestamp>=? AND timestamp<?
        """, (device_id, hour_start, hour_end))
        row = await cursor.fetchone()
        if row and row[6] and row[6] > 0:
            await db.execute("""
                INSERT INTO hourly_stats
                    (device_id, hour_start, upload_bytes, download_bytes,
                     avg_upload_bps, avg_download_bps, peak_upload_bps, peak_download_bps, sample_count)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id, hour_start) DO UPDATE SET
                    upload_bytes=excluded.upload_bytes,
                    download_bytes=excluded.download_bytes,
                    avg_upload_bps=excluded.avg_upload_bps,
                    avg_download_bps=excluded.avg_download_bps,
                    peak_upload_bps=excluded.peak_upload_bps,
                    peak_download_bps=excluded.peak_download_bps,
                    sample_count=excluded.sample_count
            """, (device_id, hour_start, row[0] or 0, row[1] or 0,
                  row[2] or 0, row[3] or 0, row[4] or 0, row[5] or 0, row[6]))
            await db.commit()


async def cleanup_old_speed_logs(days: int = 7):
    """清理超过N天的原始速度记录（保留聚合数据）"""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute("DELETE FROM speed_logs WHERE timestamp<?", (cutoff,))
        await db.commit()
        logger.info("Cleaned up %d old speed log records", result.rowcount)
