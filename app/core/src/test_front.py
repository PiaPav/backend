import asyncio
import grpc
from grpc_control.generated.api import core_pb2, core_pb2_grpc
from grpc_control.generated.shared import common_pb2

MAX_RECEIVE = 50 * 1024 * 1024 *10  # 50MB

async def grpc_collect_all(task_id: int, host: str = "localhost", port: int = 50051):
    """
    Получаем все сообщения по задаче task_id с сервера Core.
    """
    options = [('grpc.max_receive_message_length', MAX_RECEIVE)]
    channel = grpc.aio.insecure_channel(f"{host}:{port}", options=options)
    stub = core_pb2_grpc.FrontendStreamServiceStub(channel)

    all_messages = []
    seen_ids = set()

    request = core_pb2.AlgorithmRequest(user_id=1, task_id=task_id)
    print(f"📡 Подключаемся к Core RunAlgorithm(task_id={task_id})...")

    try:
        async for msg in stub.RunAlgorithm(request):
            if msg.response_id in seen_ids:
                continue
            seen_ids.add(msg.response_id)
            all_messages.append(msg)
            typ = msg.WhichOneof("graph_part_type")
            print(f"✅ task_id={msg.task_id}, response_id={msg.response_id}, type={typ}")

    except grpc.aio.AioRpcError as e:
        print("❌ Ошибка RPC:", e)

    finally:
        await channel.close()

    # Сортируем по response_id
    all_messages.sort(key=lambda m: m.response_id)
    print(f"\n📊 Всего сообщений собрано: {len(all_messages)}")
    return all_messages


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        task_id = int(sys.argv[1])
    else:
        task_id = 7 # значение по умолчанию

    asyncio.run(grpc_collect_all(task_id))
