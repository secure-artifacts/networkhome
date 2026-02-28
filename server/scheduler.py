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
    """每天凌晨3点执行：清理超过35天的原始记录"""
    await cleanup_old_speed_logs(days=35)
    logger.info("Daily cleanup done")


def start_scheduler():
    scheduler.add_job(run_hourly_aggregation, CronTrigger(minute=1))   # 每小时第1分钟
    scheduler.add_job(run_daily_cleanup, CronTrigger(hour=3, minute=0)) # 每天3:00
    # 启动时立刻跑一次聚合（填历史数据，不用等下一个整点）
    scheduler.add_job(run_startup_aggregation, 'date')
    scheduler.start()
    logger.info("Scheduler started")


async def run_startup_aggregation():
    """启动时聚合过去24小时的所有整点数据（确保历史数据进入 hourly_stats）"""
    now = datetime.now(timezone.utc)
    devices = await get_all_devices()
    # 聚合最近 24 个整点（包括当前正在进行的小时）
    for h in range(25):
        hour_start = datetime(now.year, now.month, now.day, now.hour, tzinfo=timezone.utc).timestamp() - h * 3600
        for device in devices:
            try:
                await aggregate_hour(device["id"], hour_start)
            except Exception as e:
                logger.error("Startup aggregation failed device=%s hour=%s: %s", device["id"], h, e)
    logger.info("Startup aggregation done for %d devices, past 25 hours", len(devices))


def stop_scheduler():
    scheduler.shutdown()
