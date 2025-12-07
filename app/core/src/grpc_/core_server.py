import asyncio
from typing import Dict, List

import grpc

import grpc_control.generated.api.algorithm_pb2_grpc as algorithm_pb2_grpc
import grpc_control.generated.api.core_pb2_grpc as core_pb2_grpc
import grpc_control.generated.shared.common_pb2 as common_pb2
from utils.logger import create_logger

log = create_logger("CoreGRPC")


class TaskSession:
    def __init__(self, task_id: int):
        self.task_id = task_id
        self.all_messages: List[common_pb2.GraphPartResponse] = []
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.frontend_connected = False  # один фронт
        self.algorithm_connected = False
        self.finished = False

    async def add_message(self, message: common_pb2.GraphPartResponse):
        log.info(f"[TASK_SESSION] Добавлено сообщение {message} для задачи {self.task_id}")
        self.all_messages.append(message)
        # Если фронт подключен, сразу помещаем в очередь
        if self.frontend_connected:
            await self.message_queue.put(message)

    async def mark_done(self):
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
            log.info(f"[TASK_MANAGER] Удаляем task_id={task_id}")
            del self.tasks[task_id]



class FrontendStreamService(core_pb2_grpc.FrontendStreamServiceServicer):
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def RunAlgorithm(self, request, context):
        task_session = self.task_manager.get_or_create_session(request.task_id)
        task_session.frontend_connected = True

        log.info(f"[FRONT] Подключен фронт task_id={request.task_id}")
        log.info(f"[FRONT] Статус сессии: id={task_session.task_id}, messages={len(task_session.all_messages)}, queue={len(task_session.message_queue)}")

        # Если фронт подключился позже, помещаем все накопленные сообщения в очередь
        for msg in task_session.all_messages:
            log.info(f"[FRONT] В очередь добавлено сообщение {msg}")
            await task_session.message_queue.put(msg)

        try:
            while True:
                try:
                    message = await asyncio.wait_for(task_session.message_queue.get(), timeout=0.1)
                    log.info(f"[FRONT] Отдано сообщение {message}")
                    yield message
                except asyncio.TimeoutError:
                    # Если задача завершена и очередь пуста, заканчиваем поток
                    if task_session.finished and task_session.message_queue.empty():
                        log.info(f"[FRONT] Задача {request.task_id} завершена, закрываем поток")
                        break
        finally:
            task_session.frontend_connected = False
            # Очистка сессии после того, как фронт отключился и задача завершена
            if task_session.finished and not task_session.frontend_connected:
                log.info(f"[TASK_MANAGER] Удаляем task_id={task_session.task_id}")
                self.task_manager.remove_session(task_session.task_id)



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

            log.info(f"[ALG] task={message.task_id}, status={message.status}")

            await task_session.add_message(message)

            if message.status == common_pb2.ParseStatus.DONE:
                await task_session.mark_done()
                log.info(f"[ALG] DONE получен для task={task_session.task_id}")

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
        #await self.server.wait_for_termination()

    async def stop(self):
        log.info("CoreServer: остановка")
        await self.server.stop(0)
