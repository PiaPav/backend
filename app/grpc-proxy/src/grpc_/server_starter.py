import asyncio
from grpc_.core_server import CoreServer
from utils.logger import create_logger

log = create_logger("GRPC")
_core_server = CoreServer()
_grpc_task: asyncio.Task | None = None

async def start_grpc():
    await _core_server.start()


async def _keep_running():
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass

async def stop_grpc():
    global _grpc_task
    if _grpc_task:
        _grpc_task.cancel()
        try:
            await _grpc_task
        except asyncio.CancelledError:
            pass
    await _core_server.stop()
