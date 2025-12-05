import asyncio
import grpc
import sys

from grpc_control.generated.api import core_pb2
from grpc_control.generated.api import core_pb2_grpc


async def run_frontend_test(task_id: int, host: str = "78.153.139.47", port: int = 8080):
    channel = grpc.aio.insecure_channel(f"{host}:{port}")
    stub = core_pb2_grpc.FrontendStreamServiceStub(channel)

    print(f"📡 Подключаюсь к Core RunAlgorithm(task_id={task_id})...")

    try:
        # Запрос аналогичен тому, что отправляет фронтенд:
        request = core_pb2.AlgorithmRequest(
            user_id=1,
            task_id=task_id
        )

        # Устанавливаем streaming-соединение
        async for message in stub.RunAlgorithm(request):
            print("✅ Получено сообщение от Core:")
            print(message)

        print("⚠️ Поток завершён")

    except grpc.aio.AioRpcError as e:
        print("❌ Ошибка RPC:", e)

    finally:
        await channel.close()


if __name__ == "__main__":
    # Берем task_id из аргументов командной строки, если передан
    if len(sys.argv) > 1:
        task_id = int(sys.argv[1])
    else:
        task_id = 23# значение по умолчанию

    asyncio.run(run_frontend_test(task_id=task_id))