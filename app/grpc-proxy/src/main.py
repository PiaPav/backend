import asyncio
from grpc_.core_server import CoreServer
from utils.logger import create_logger

log = create_logger("CoreGRPCMain")


async def main():
    server = CoreServer(host='0.0.0.0', port=50051)
    await server.start()
    log.info(f"gRPC CoreServer запущен на {server.port}")

    try:
        await server.server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop()
        log.info("gRPC CoreServer остановлен")

if __name__ == "__main__":
    asyncio.run(main())
