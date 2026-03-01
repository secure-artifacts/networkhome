"""
数据库管理模块 - 创建表结构、提供读写接口
"""
import aiosqlite
import os
import logging
from datetime import datetime, timezone

# 路径支持环境变量覆盖（server_tray.py 打包时设置 NM_DB_PATH）
DB_PATH = os.environ.get("NM_DB_PATH", os.path.join(os.path.dirname(__file__), "netmonitor.db"))
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


async def rename_device(device_id: str, new_name: str) -> bool:
    """重命名设备，返回是否成功"""
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute(
            "UPDATE devices SET name=? WHERE id=?",
            (new_name.strip(), device_id)
        )
        await db.commit()
        return result.rowcount > 0


async def delete_device(device_id: str) -> bool:
    """删除设备及其所有历史数据"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM speed_logs   WHERE device_id=?", (device_id,))
        await db.execute("DELETE FROM hourly_stats WHERE device_id=?", (device_id,))
        result = await db.execute("DELETE FROM devices WHERE id=?", (device_id,))
        await db.commit()
        return result.rowcount > 0


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

async def get_hourly_stats_all(since_ts: float, until_ts: float | None = None):
    """获取全网所有设备合计的小时聚合数据"""
    until_ts = until_ts or (datetime.now(timezone.utc).timestamp() + 1)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT hour_start, 
                   SUM(upload_bytes) AS upload_bytes, 
                   SUM(download_bytes) AS download_bytes,
                   AVG(avg_upload_bps) AS avg_upload_bps, 
                   AVG(avg_download_bps) AS avg_download_bps, 
                   SUM(peak_upload_bps) AS peak_upload_bps, 
                   SUM(peak_download_bps) AS peak_download_bps
            FROM hourly_stats
            WHERE hour_start>=? AND hour_start<=?
            GROUP BY hour_start
            ORDER BY hour_start ASC
        """, (since_ts, until_ts))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_weekly_heatmap(weeks: int = 4):
    """全设备合计，按星期几(0=周日)+小时 聚合，返回 7×24 矩阵"""
    since = datetime.now(timezone.utc).timestamp() - weeks * 7 * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                CAST(strftime('%w', datetime(hour_start,'unixepoch', 'localtime')) AS INTEGER) AS dow,
                CAST(strftime('%H', datetime(hour_start,'unixepoch', 'localtime')) AS INTEGER) AS hr,
                AVG(upload_bytes)   AS avg_up,
                AVG(download_bytes) AS avg_down,
                MAX(upload_bytes)   AS peak_up,
                MAX(download_bytes) AS peak_down
            FROM hourly_stats
            WHERE hour_start >= ?
            GROUP BY dow, hr
        """, (since,))
        rows = await cursor.fetchall()
        matrix = {d: {h: {"avg_up": 0, "avg_down": 0} for h in range(24)} for d in range(7)}
        for r in rows:
            matrix[r["dow"]][r["hr"]] = {"avg_up": r["avg_up"] or 0, "avg_down": r["avg_down"] or 0}
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
                CAST(strftime('%w', datetime(hour_start,'unixepoch', 'localtime')) AS INTEGER) AS dow,
                CAST(strftime('%H', datetime(hour_start,'unixepoch', 'localtime')) AS INTEGER) AS hr,
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


async def get_daily_stats(year: int, month: int):
    """
    返回指定年月内每天的全设备合计流量。
    结果: [{date: "YYYY-MM-DD", upload_bytes, download_bytes}, ...]
    """
    import calendar
    import time
    
    first_day_local = datetime(year, month, 1)
    since = first_day_local.astimezone().timestamp()

    last_day_num = calendar.monthrange(year, month)[1]
    last_day_local = datetime(year, month, last_day_num, 23, 59, 59)
    until = last_day_local.astimezone().timestamp()
    
    current_utc_hour_start = int(time.time() // 3600 * 3600)
    rt_since = max(since, current_utc_hour_start)
    if rt_since > until:
        rt_since = until + 1

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Determine the last aggregated hour to cleanly append real-time data
        cursor_hr = await db.execute("SELECT MAX(hour_start) as max_hr FROM hourly_stats")
        row_hr = await cursor_hr.fetchone()
        last_hr = float(row_hr["max_hr"]) if row_hr and row_hr["max_hr"] else 0.0
        
        # rt_since needs to start right after the last aggregated hour, or from `since` if no aggregations exist
        rt_since = max(since, last_hr + 3600 if last_hr > 0 else 0)
        
        if rt_since > until:
            rt_since = until + 1

        query = """
        WITH HourlyData AS (
            SELECT
                strftime('%Y-%m-%d', datetime(hour_start, 'unixepoch', 'localtime')) AS date,
                SUM(upload_bytes)   AS upload_bytes,
                SUM(download_bytes) AS download_bytes
            FROM hourly_stats
            WHERE hour_start >= ? AND hour_start <= ?
            GROUP BY date
        ),
        RtData AS (
            SELECT
                strftime('%Y-%m-%d', datetime(timestamp, 'unixepoch', 'localtime')) AS date,
                SUM(upload_bps)/8.0   AS upload_bytes,
                SUM(download_bps)/8.0 AS download_bytes
            FROM speed_logs
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY date
        )
        SELECT date, SUM(upload_bytes) as upload_bytes, SUM(download_bytes) as download_bytes
        FROM (SELECT * FROM HourlyData UNION ALL SELECT * FROM RtData)
        GROUP BY date
        ORDER BY date ASC
        """
        cursor = await db.execute(query, (since, until, rt_since, until))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_aggregate_speed_history(seconds: int = 300, from_ts: int = 0, to_ts: int = 0):
    """
    获取全网合计的降采样数据。
    支持通过 seconds 或 from_ts/to_ts 取时间段，并将点数控制在 300 左右。
    """
    if from_ts > 0 and to_ts > 0:
        actual_from = from_ts
        actual_to = to_ts
    else:
        actual_to = int(datetime.now(timezone.utc).timestamp())
        actual_from = actual_to - seconds

    span_sec = max(1, actual_to - actual_from)
    bucket_size = max(1, span_sec // 300)

    query = """
        WITH DeviceAvg AS (
            SELECT 
                (CAST(timestamp AS INTEGER) / ?) * ? AS ts_bucket,
                device_id,
                AVG(upload_bps) AS dev_up,
                AVG(download_bps) AS dev_down
            FROM speed_logs
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY ts_bucket, device_id
        )
        SELECT 
            ts_bucket AS timestamp,
            SUM(dev_up) AS upload_bps,
            SUM(dev_down) AS download_bps
        FROM DeviceAvg
        GROUP BY ts_bucket
        ORDER BY ts_bucket ASC
    """

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, (bucket_size, bucket_size, actual_from, actual_to))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_aggregate_speed_device(device_id: str, seconds: int = 300, from_ts: int = 0, to_ts: int = 0):
    """
    获取指定设备的降采样时序数据。
    支持通过 seconds 或 from_ts/to_ts 取时间段，并将点数控制在 300 左右。
    """
    if from_ts > 0 and to_ts > 0:
        actual_from = from_ts
        actual_to = to_ts
    else:
        actual_to = int(datetime.now(timezone.utc).timestamp())
        actual_from = actual_to - seconds

    span_sec = max(1, actual_to - actual_from)
    bucket_size = max(1, span_sec // 300)

    query = """
        SELECT 
            (CAST(timestamp AS INTEGER) / ?) * ? AS timestamp,
            AVG(upload_bps) AS upload_bps,
            AVG(download_bps) AS download_bps
        FROM speed_logs
        WHERE device_id = ? AND timestamp >= ? AND timestamp <= ?
        GROUP BY timestamp
        ORDER BY timestamp ASC
    """

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, (bucket_size, bucket_size, device_id, actual_from, actual_to))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

