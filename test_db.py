import asyncio
from database import get_aggregate_speed_history, get_aggregate_speed_device
from datetime import datetime, timezone

async def test():
    print("Now UTC:", datetime.now(timezone.utc).timestamp())
    rows = await get_aggregate_speed_history(1800)
    print("History (1800s):", len(rows))
    if rows:
        print("  First:", rows[0])
        print("  Last:", rows[-1])

    rows = await get_aggregate_speed_device('1', 1800)
    print("Device 1 (1800s):", len(rows))

asyncio.run(test())
