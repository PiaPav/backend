# core_server.py
from typing import Dict

import grpc

import grpc_control.generated.api.algorithm_pb2_grpc as algorithm_pb2_grpc
import grpc_control.generated.api.core_pb2_grpc as core_pb2_grpc
import grpc_control.generated.shared.common_pb2 as common_pb2
from utils.logger import create_logger

log = create_logger("CoreGRPC")


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
        self.finished = False  # ✅ основной признак завершения

    async def add_message(self, message: common_pb2.GraphPartResponse):
        """Добавить сообщение от Algorithm."""
        await self.message_queue.put(message)

    async def get_next_message(self):
        """Получить следующее сообщение для фронтенда."""
        return await self.message_queue.get()

    async def mark_done(self):
        """Пометить сессию завершённой."""
        self.finished = True


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
class FrontendStreamService(core_pb2_grpc.FrontendStreamServiceServicer):
    """Сервис для фронтенда: RunAlgorithm (server-streaming)."""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def RunAlgorithm(self, request, context):
        task_session = self.task_manager.get_or_create_session(request.task_id)
        task_session.frontend_connected = True

        log.info(f"[FRONT] RunAlgorithm: ожидание сообщений task_id={request.task_id}")

        try:
            while True:
                # Если алгоритм сказал DONE — прекращаем стрим
                if task_session.finished and task_session.message_queue.empty():
                    log.info(f"[FRONT] Задача {request.task_id} завершена, закрываем поток")
                    break

                message = await task_session.get_next_message()
                yield message
        except Exception as e:
            log.error(f"[FRONT] Ошибка RunAlgorithm: {e}")
        finally:
            self.task_manager.remove_session(request.task_id)


class AlgorithmConnectionService(algorithm_pb2_grpc.AlgorithmConnectionServiceServicer):
    """Сервис для алгоритма: ConnectToCore (client-streaming)."""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def ConnectToCore(self, request_iterator, context):
        task_session: TaskSession | None = None

        async for message in request_iterator:
            if task_session is None:
                task_session = self.task_manager.get_or_create_session(message.task_id)
                task_session.algorithm_connected = True

            log.info(f"Алгоритм msg task={message.task_id}, status={message.status}")

            # ✅ Если алгоритм прислал DONE — отмечаем завершение
            if message.status == common_pb2.ParseStatus.DONE:
                await task_session.add_message(message)
                await task_session.mark_done()
                log.info(f"Алгоритм получен DONE для task={task_session.task_id}")
            else:
                await task_session.add_message(message)

        # ✅ НЕ ЗАКРЫВАЕМ СЕССИЮ!
        # Сессия будет закрыта фронтом после DONE

        return common_pb2.Empty()


# ===========================
# ==== CoreServer (запуск) ==
# ===========================
class CoreServer:
    def __init__(self, host='[::]', port=50051):
        self.task_manager = TaskManager()
        self.host = host
        self.port = port

        self.frontend_service = FrontendStreamService(self.task_manager)
        self.algorithm_service = AlgorithmConnectionService(self.task_manager)

        self.server = grpc.aio.server()

        core_pb2_grpc.add_FrontendStreamServiceServicer_to_server(
            self.frontend_service, self.server
        )
        algorithm_pb2_grpc.add_AlgorithmConnectionServiceServicer_to_server(
            self.algorithm_service, self.server
        )

        self.server.add_insecure_port(f'{self.host}:{self.port}')

    async def start(self):
        log.info(f"CoreServer: запуск на {self.host}:{self.port}")
        await self.server.start()

    async def stop(self):
        log.info("CoreServer: остановка")
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
