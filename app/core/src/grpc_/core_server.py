import asyncio
from typing import Dict, List

import grpc

import grpc_control.generated.api.algorithm_pb2_grpc as algorithm_pb2_grpc
import grpc_control.generated.api.core_pb2_grpc as core_pb2_grpc
import grpc_control.generated.shared.common_pb2 as common_pb2
from utils.logger import create_logger

log = create_logger("CoreGRPC")


class TaskSession:
    """Контекст одной задачи (task_id)."""

    def __init__(self, task_id: int):
        self.task_id = task_id
        self.message_queue = asyncio.Queue()
        self.all_messages: List[common_pb2.GraphPartResponse] = []
        self.frontend_connected = set()  # теперь может быть несколько фронтов
        self.algorithm_connected = False
        self.finished = False  # основной признак завершения

    async def add_message(self, message: common_pb2.GraphPartResponse):
        """Добавить сообщение от Algorithm и отправить live всем фронтам."""
        self.all_messages.append(message)

        # Посылаем live-сообщение всем подключённым фронтам
        for ctx in list(self.frontend_connected):
            try:
                await ctx.write(message)  # ctx — контекст фронтенда
            except Exception as e:
                log.warning(f"[FRONT] Ошибка при отправке live-сообщения: {e}")

        await self.message_queue.put(message)

    async def get_next_message(self):
        """Получить следующее сообщение для фронтенда."""
        return await self.message_queue.get()

    def get_all_messages(self):
        """Возвращает уже отправленные сообщения (для поздних фронтов)."""
        return list(self.all_messages)

    async def mark_done(self):
        """Пометить сессию завершённой."""
        self.finished = True


class TaskManager:
    """Управляет всеми активными задачами."""

    def __init__(self):
        self.tasks: Dict[int, TaskSession] = {}

    def get_or_create_session(self, task_id: int) -> TaskSession:
        if task_id not in self.tasks:
            log.info(f"[TASK_MANAGER] Created new TaskSession for task_id={task_id}")
            self.tasks[task_id] = TaskSession(task_id)
        return self.tasks[task_id]

    def remove_session(self, task_id: int):
        """Удалить сессию, освобождая память."""
        if task_id in self.tasks:
            log.info(f"[TASK_MANAGER] Removing TaskSession task_id={task_id}")
            del self.tasks[task_id]


class FrontendStreamService(core_pb2_grpc.FrontendStreamServiceServicer):
    """Сервис для фронтенда: RunAlgorithm (server-streaming)."""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def RunAlgorithm(self, request, context):
        task_session = self.task_manager.get_or_create_session(request.task_id)
        task_session.frontend_connected.add(context)

        log.info(f"[FRONT] Подключен фронт task_id={request.task_id}")

        # Отдать все накопленные сообщения (backlog)
        for msg in task_session.get_all_messages():
            yield msg

        # Ждать новые сообщения до завершения задачи
        try:
            while not task_session.finished or not task_session.message_queue.empty():
                try:
                    message = await asyncio.wait_for(task_session.get_next_message(), timeout=0.1)
                    yield message
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            log.error(f"[FRONT] Ошибка RunAlgorithm: {e}")
        finally:
            task_session.frontend_connected.discard(context)
            if task_session.finished and not task_session.frontend_connected:
                log.info(f"[FRONT] Task {request.task_id} полностью завершена")
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
                log.info(f"[ALG CONNECT] ctx_alg task_id={message.task_id} connected; listeners=0 backlog=0")

            log.info(f"[ALG MSG] task={message.task_id} response_id={message.response_id} status={message.status} type={message.WhichOneof('msg_type')}")

            await task_session.add_message(message)

            if message.status == common_pb2.ParseStatus.DONE:
                await task_session.mark_done()
                log.info(f"[SESSION {task_session.task_id}] mark_done: finished=True")
                log.info(f"[ALG DONE] task={task_session.task_id} received DONE (response_id={message.response_id})")

        log.info(f"[ALG STREAM END] ConnectToCore completed for task={task_session.task_id if task_session else 'unknown'}")
        return common_pb2.Empty()


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
        await self.server.wait_for_termination()

    async def stop(self):
        log.info("CoreServer: остановка")
        await self.server.stop(0)


# Для запуска вручную
# if __name__ == "__main__":
#     import asyncio
#     core_server = CoreServer()
#     try:
#         asyncio.run(core_server.start())
#     except KeyboardInterrupt:
#         asyncio.run(core_server.stop())
