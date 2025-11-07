# algorithm_client.py
import grpc
from grpc_control.generated.shared import common_pb2
from grpc_control.generated.api import algorithm_pb2_grpc


class AlgorithmClient:
    """
    Универсальный клиент:
    - можно вызывать send(...), передавая список данных или один объект
    - можно вызывать stream(...), передавая async generator
    """

    def __init__(self, core_host: str = "localhost", core_port: int = 50051):
        self.core_address = f"{core_host}:{core_port}"

    # ===========================
    # ===== send() — простой способ =====
    # ===========================

    async def send(self, task_id: int, data):
        """
        Отправляет данные в Core.
        data может быть:
            - GraphPartResponse (готовый proto)
            - dict, из которого можно собрать proto
            - tuple ("parent", ["children"])
            - список/кортеж любых из этих типов
        """

        async def generator():
            # Если список или tuple
            if isinstance(data, (list, tuple)):
                for item in data:
                    yield self._prepare_msg(task_id, item)
            else:
                # Единичное значение
                yield self._prepare_msg(task_id, data)

        await self._send_stream(generator())

    # ===========================
    # ===== stream() — продвинуто =====
    # ===========================

    async def stream(self, task_id: int, async_iter):
        """
        Передаёшь генератор, который yield-ит элементы для GraphPartResponse.
        """

        async def generator():
            async for item in async_iter:
                yield self._prepare_msg(task_id, item)

        await self._send_stream(generator())

    # ===========================
    # ===== внутренние методы =====
    # ===========================

    async def _send_stream(self, msg_stream):
        """Открывает gRPC канал и отправляет поток сообщений."""
        async with grpc.aio.insecure_channel(self.core_address) as channel:
            stub = algorithm_pb2_grpc.AlgorithmConnectionServiceStub(channel)
            await stub.ConnectToCore(msg_stream)

    # ===========================
    # ===== message builder =====
    # ===========================

    def _prepare_msg(self, task_id: int, item) -> common_pb2.GraphPartResponse:
        """
        Конвертирует item в корректный GraphPartResponse.
        """

        # ✅ Если это уже готовый proto – просто вернуть
        if isinstance(item, common_pb2.GraphPartResponse):
            return item

        # ✅ dict → GraphPartResponse(**fields)
        if isinstance(item, dict):
            return common_pb2.GraphPartResponse(task_id=task_id, **item)

        # ✅ tuple вида (parent, children) → архитектура
        if isinstance(item, tuple) and len(item) == 2:
            parent, children = item
            return common_pb2.GraphPartResponse(
                task_id=task_id,
                status=common_pb2.ParseStatus.ARHITECTURE,
                graph_architecture=common_pb2.GraphPartArchitecture(
                    parent=parent,
                    children=list(children)
                )
            )

        # ❌ Если тип неизвестен – ошибка, НЕ fallback!
        raise TypeError(
            f"Unsupported item type for GraphPartResponse: {type(item)} — {item}"
        )
