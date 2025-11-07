# core_server.py
from typing import Dict
import grpc
import grpc_control.generated.shared.common_pb2 as common_pb2
import grpc_control.generated.api.core_pb2_grpc as core_pb2_grpc
import grpc_control.generated.api.algorithm_pb2_grpc as algorithm_pb2_grpc

# =============================
# ==== ВНУТРЕННИЕ СУЩНОСТИ ====
# =============================

class TaskSession:
    """Контекст одной задачи (task_id)."""
    def __init__(self, task_id: int):
        self.task_id = task_id
        self.message_queue = asyncio.Queue()
        self.frontend_connected = False
        self.algorithm_connected = False
        self.status = "WAITING"

    async def add_message(self, message: common_pb2.GraphPartResponse):
        """Добавить сообщение от Algorithm."""
        await self.message_queue.put(message)

    async def get_next_message(self):
        """Получить следующее сообщение для фронтенда."""
        message = await self.message_queue.get()
        return message

    async def close(self):
        """Закрыть сессию."""
        self.status = "DONE"


class TaskManager:
    """Управляет всеми активными задачами."""
    def __init__(self):
        self.tasks: Dict[int, TaskSession] = {}

    def get_or_create_session(self, task_id: int) -> TaskSession:
        if task_id not in self.tasks:
            self.tasks[task_id] = TaskSession(task_id)
        return self.tasks[task_id]

    def remove_session(self, task_id: int):
        if task_id in self.tasks:
            del self.tasks[task_id]

# =====================================
# ==== gRPC СЕРВИСЫ CORE-SERVER =======
# =====================================
# Эту шнягу вызовут с фронта
class FrontendStreamService(core_pb2_grpc.FrontendStreamServiceServicer):
    """Сервис для фронтенда: RunAlgorithm (server-streaming)."""
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def RunAlgorithm(self, request, context):
        """
        1. Создать или найти TaskSession
        2. В брокере уже висит задача и алгоритм начал работу
        3. Ждать и отдавать поток данных фронтенду
        """
        task_session = self.task_manager.get_or_create_session(request.task_id)
        task_session.frontend_connected = True

        try:
            while task_session.status != "DONE":
                # Ждём новые сообщения от Algorithm
                message = await task_session.get_next_message()
                # Отправляем фронту через gRPC stream
                yield message
        finally:
            # Очистка ресурсов
            await task_session.close()
            self.task_manager.remove_session(request.task_id)


class AlgorithmConnectionService(algorithm_pb2_grpc.AlgorithmConnectionServiceServicer):
    """Сервис для алгоритма: ConnectToCore (client-streaming)."""
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def ConnectToCore(self, request_iterator, context):
        """
        1. Algorithm подключается
        2. Core принимает поток GraphPartResponse
        3. Добавляет их в очередь TaskSession
        """

        task_session: TaskSession | None = None

        try:
            async for message in request_iterator:
                # Создаём / находим сессию по task_id
                if task_session is None:
                    task_session = self.task_manager.get_or_create_session(message.task_id)
                    task_session.algorithm_connected = True

                # Кладём сообщение в очередь
                await task_session.add_message(message)

        except Exception as e:
            print("ConnectToCore EXCEPTION:", e)
            # Можно дополнительно вызвать:
            # context.abort(grpc.StatusCode.INTERNAL, str(e))

        finally:
            # Если алгоритм прислал хоть одно сообщение — закрываем сессию
            if task_session is not None:
                await task_session.close()

        # ✅ ОБЯЗАТЕЛЬНО вернуть common_pb2.Empty()
        # (НЕ google.protobuf.Empty, иначе будет TypeError SerializeToString)
        return common_pb2.Empty()



# ===========================
# ==== CoreServer (запуск) ==
# ===========================

class CoreServer:
    """Главный сервер Core, объединяющий оба сервиса."""
    def __init__(self, host='[::]', port=50051):
        self.task_manager = TaskManager()
        self.host = host
        self.port = port

        # gRPC сервисы
        self.frontend_service = FrontendStreamService(self.task_manager)
        self.algorithm_service = AlgorithmConnectionService(self.task_manager)

        # gRPC сервер
        self.server = grpc.aio.server()

        # Регистрация сервисов на сервере
        core_pb2_grpc.add_FrontendStreamServiceServicer_to_server(
            self.frontend_service, self.server
        )
        algorithm_pb2_grpc.add_AlgorithmConnectionServiceServicer_to_server(
            self.algorithm_service, self.server
        )

        # Указываем порт
        self.server.add_insecure_port(f'{self.host}:{self.port}')

    async def start(self):
        """Запуск gRPC сервера и ожидание входящих соединений."""
        print(f"CoreServer: запуск на {self.host}:{self.port}")
        await self.server.start()
        # Ожидание завершения сервера
        await self.server.wait_for_termination()

    async def stop(self):
        """Остановка сервера и закрытие всех TaskSession."""
        print("CoreServer: остановка")
        for task_id, session in list(self.task_manager.tasks.items()):
            await session.close()
            self.task_manager.remove_session(task_id)
        await self.server.stop(0)


# ===========================
# ==== Запуск через main ====
# ===========================

if __name__ == "__main__":
    import asyncio

    core_server = CoreServer()

    try:
        asyncio.run(core_server.start())
    except KeyboardInterrupt:
        print("CoreServer: получен сигнал остановки")
        asyncio.run(core_server.stop())
