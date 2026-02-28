"""
定时任务调度器 - 每小时聚合数据，每天清理旧数据
"""
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from database import aggregate_hour, cleanup_old_speed_logs, get_all_devices

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


async def run_hourly_aggregation():
    """每小时执行：对所有设备聚合上一小时数据"""
    now = datetime.now(timezone.utc)
    # 对上一小时做聚合
    hour_start = datetime(now.year, now.month, now.day, now.hour, tzinfo=timezone.utc).timestamp() - 3600
    devices = await get_all_devices()
    for device in devices:
        try:
            await aggregate_hour(device["id"], hour_start)
        except Exception as e:
            logger.error("Aggregation failed for device %s: %s", device["id"], e)
    logger.info("Hourly aggregation done for hour starting %s", datetime.fromtimestamp(hour_start, tz=timezone.utc))


async def run_daily_cleanup():
    """每天凌晨3点执行：清理超过7天的原始记录"""
    await cleanup_old_speed_logs(days=7)
    logger.info("Daily cleanup done")


def start_scheduler():
    scheduler.add_job(run_hourly_aggregation, CronTrigger(minute=1))   # 每小时第1分钟
    scheduler.add_job(run_daily_cleanup, CronTrigger(hour=3, minute=0)) # 每天3:00
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler():
    scheduler.shutdown()
