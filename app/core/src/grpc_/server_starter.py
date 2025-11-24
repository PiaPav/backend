import asyncio

from grpc_.core_server import CoreServer
from grpc_.core_server import CoreServer
from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("StarterGRPC")

server: CoreServer | None = None

async def start_grpc():
    global server
    log.info("gRPC сервер стартует...")

    # ❗ Создаём сервер ВНУТРИ ТОГО ЖЕ loop, где FastAPI живёт
    server = CoreServer(host=CONFIG.grpc.host, port=CONFIG.grpc.port)
    await server.start()

async def stop_grpc():
    global server
    if server:
        log.info("gRPC сервер остановлен")
        await server.stop()


# if __name__ == "__main__":
#     try:
#         asyncio.run(start_grpc())
#     except KeyboardInterrupt:
#         print("⛔ Сервер остановлен вручную")
