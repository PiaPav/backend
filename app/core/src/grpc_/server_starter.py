import asyncio

from grpc_.core_server import CoreServer
from grpc_.core_server import CoreServer
from utils.logger import create_logger

log = create_logger("StarterGRPC")

server: CoreServer | None = None

async def start_grpc():
    global server
    log.info("gRPC сервер стартует...")

    # ❗ Создаём сервер ВНУТРИ ТОГО ЖЕ loop, где FastAPI живёт
    server = CoreServer(host="0.0.0.0", port=50051)
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
