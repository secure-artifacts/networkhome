"""
UDP 广播服务 - 服务器每3秒广播自己的地址，客户端自动发现
广播端口: 8867
"""
import asyncio
import json
import socket
import logging

logger = logging.getLogger(__name__)

BROADCAST_PORT = 8867
BROADCAST_INTERVAL = 3  # 秒


async def run_broadcaster(http_port: int = 8866):
    """持续广播服务器位置，让 Agent 无需手动输入 IP"""
    payload = json.dumps({
        "service": "netmonitor",
        "port": http_port,
        "version": "2.0.1"
    }).encode()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)

    logger.info("UDP broadcaster started on port %d (broadcasting every %ds)", BROADCAST_PORT, BROADCAST_INTERVAL)

    loop = asyncio.get_event_loop()
    while True:
        try:
            await loop.run_in_executor(
                None,
                lambda: sock.sendto(payload, ("<broadcast>", BROADCAST_PORT))
            )
        except Exception as e:
            logger.debug("Broadcast error (normal on some OS): %s", e)
        await asyncio.sleep(BROADCAST_INTERVAL)
