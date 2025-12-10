import grpc
import asyncio
from grpc_reflection.v1alpha import reflection
from grpc_control.generated.api import core_pb2_grpc, algorithm_pb2_grpc, core_pb2, algorithm_pb2
from grpc_control.generated.shared import common_pb2
from utils.logger import create_logger

log = create_logger("CoreGRPC")

class TaskSession:
    def __init__(self, task_id: int):
        self.task_id = task_id
        self.message_queue = asyncio.Queue()
        self.all_messages = []
        self.frontend_connected = set()
        self.finished = False

    async def add_message(self, msg: common_pb2.GraphPartResponse):
        self.all_messages.append(msg)
        await self.message_queue.put(msg)

    async def get_next_message(self):
        return await self.message_queue.get()

    def get_all_messages(self):
        return list(self.all_messages)

    async def mark_done(self):
        self.finished = True


class TaskManager:
    def __init__(self):
        self.tasks = {}

    def get_or_create_session(self, task_id: int):
        if task_id not in self.tasks:
            self.tasks[task_id] = TaskSession(task_id)
        return self.tasks[task_id]

    def remove_session(self, task_id: int):
        if task_id in self.tasks:
            del self.tasks[task_id]

class FrontendStreamService(core_pb2_grpc.FrontendStreamServiceServicer):
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def RunAlgorithm(self, request, context):
        session = self.task_manager.get_or_create_session(request.task_id)
        session.frontend_connected.add(context)

        log.info(f"[FRONT] Подключён фронтенд task_id={request.task_id}")

        # Отдаём уже накопленные сообщения
        for msg in session.get_all_messages():
            log.info(f"[FRONT] → Отдаём накопленное сообщение на фронт: {msg}")
            log.info(f"[FRONT] Детали сообщения:\n{msg}")

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(session.get_next_message(), timeout=0.1)

                    # Логируем САМО сообщение перед отправкой
                    log.info(f"[FRONT] → Отдаём новое сообщение на фронт: {msg}")
                    log.info(f"[FRONT] Детали сообщения:\n{msg}")

                    yield msg

                except asyncio.TimeoutError:
                    if session.finished and session.message_queue.empty():
                        log.info(
                            f"[FRONT] Завершаем отдачу сообщений task_id={request.task_id}"
                        )
                        break

        finally:
            session.frontend_connected.discard(context)
            log.info(f"[FRONT] Отключение фронтенда task_id={request.task_id}")

            if session.finished and not session.frontend_connected and session.message_queue.empty():
                self.task_manager.remove_session(request.task_id)
                log.info(f"[TASK_MANAGER] Полная очистка task_id={request.task_id}")



class AlgorithmConnectionService(algorithm_pb2_grpc.AlgorithmConnectionServiceServicer):
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def ConnectToCore(self, request_iterator, context):
        session = None
        async for msg in request_iterator:
            if session is None:
                session = self.task_manager.get_or_create_session(msg.task_id)
            await session.add_message(msg)
            if msg.status == common_pb2.ParseStatus.DONE:
                await session.mark_done()
        return common_pb2.Empty()

class CoreServer:
    def __init__(self, host='0.0.0.0', port=50051):
        self.task_manager = TaskManager()
        self.server = grpc.aio.server()

        # Регистрируем сервисы
        core_pb2_grpc.add_FrontendStreamServiceServicer_to_server(
            FrontendStreamService(self.task_manager), self.server
        )
        algorithm_pb2_grpc.add_AlgorithmConnectionServiceServicer_to_server(
            AlgorithmConnectionService(self.task_manager), self.server
        )

        # Включаем рефлексию
        SERVICE_NAMES = (
            core_pb2.DESCRIPTOR.services_by_name['FrontendStreamService'].full_name,
            algorithm_pb2.DESCRIPTOR.services_by_name['AlgorithmConnectionService'].full_name,
            reflection.SERVICE_NAME,
        )
        reflection.enable_server_reflection(SERVICE_NAMES, self.server)

        # Порт
        self.port = self.server.add_insecure_port(f'{host}:{port}')

    async def start(self):
        await self.server.start()
        log.info(f"gRPC CoreServer запущен на порту {self.port}")

    async def stop(self):
        await self.server.stop(0)
        log.info("gRPC CoreServer остановлен")

