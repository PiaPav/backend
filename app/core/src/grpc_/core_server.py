# core_server.py
import asyncio
from typing import Dict, List, Any

import grpc

import grpc_control.generated.api.algorithm_pb2_grpc as algorithm_pb2_grpc
import grpc_control.generated.api.core_pb2_grpc as core_pb2_grpc
import grpc_control.generated.shared.common_pb2 as common_pb2
from utils.logger import create_logger

log = create_logger("CoreGRPC")


class TaskSession:
    """
    Контекст одной задачи (task_id).
    Хранит:
      - all_messages: полный список сообщений (history)
      - frontend_queues: отдельная очередь сообщений для каждого подключённого фронта
      - algorithm_connected: флаг, что алгоритм подключён
      - finished: флаг, что алгоритм прислал DONE
    """
    def __init__(self, task_id: int):
        self.task_id = task_id
        self.all_messages: List[common_pb2.GraphPartResponse] = []
        # ключ — context (объект запроса), значение — asyncio.Queue
        self.frontend_queues: Dict[Any, asyncio.Queue] = {}
        self.algorithm_connected = False
        self.finished = False

        # лок для ожидания, например, при тестах — можно ждать появления новых сообщений
        self._new_message_event = asyncio.Event()

    async def add_message(self, message: common_pb2.GraphPartResponse):
        """Добавить сообщение от Algorithm: сохраняем в историю и пушим во все очереди фронтов."""
        # Сохраняем
        self.all_messages.append(message)
        log.debug(f"[SESSION {self.task_id}] add_message: saved response_id={message.response_id} status={message.status} type={message.WhichOneof('graph_part_type')} (total_saved={len(self.all_messages)})")

        # Сигнал для любого ожидающего потока
        self._new_message_event.set()
        # Сбрасываем событие (оно останется установленным до следующего put, очистим)
        self._new_message_event.clear()

        # Кладём в очереди фронтов (попытаемся put_nowait — не блокировать)
        for ctx, queue in list(self.frontend_queues.items()):
            try:
                queue.put_nowait(message)
                log.debug(f"[SESSION {self.task_id}] queued message response_id={message.response_id} -> front_ctx={id(ctx)}")
            except asyncio.QueueFull:
                # Если очередь переполнена (в теории), логируем и делаем await put (чтобы не потерять)
                log.warning(f"[SESSION {self.task_id}] FRONT queue full for ctx={id(ctx)}; awaiting put() for response_id={message.response_id}")
                try:
                    await queue.put(message)
                    log.debug(f"[SESSION {self.task_id}] queued (after await) response_id={message.response_id} -> front_ctx={id(ctx)}")
                except Exception as e:
                    log.error(f"[SESSION {self.task_id}] Failed to put message into queue for ctx={id(ctx)}: {e}")

    def register_frontend(self, context) -> asyncio.Queue:
        """
        Регистрируем нового фронта: создаём очередь и наполняем backlog-ом.
        Возвращаем очередь, из которой фронт будет читать.
        """
        queue: asyncio.Queue = asyncio.Queue()
        # Копируем backlog в очередь (put_nowait, backlog гарантированно хранится в памяти)
        for msg in self.all_messages:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                # Невероятный случай, делаем await
                log.warning(f"[SESSION {self.task_id}] register_frontend: queue full when pushing backlog, doing await.put()")
                # очередь пока пуста и маловероятно будет full; использовать put_nowait в цикле безопасно
                # но на всякий случай:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(queue.put(msg))  # sync fallback (редко)
        self.frontend_queues[context] = queue
        log.info(f"[SESSION {self.task_id}] register_frontend: ctx={id(context)} queue_size={queue.qsize()} (backlog_copied={len(self.all_messages)}) listeners={len(self.frontend_queues)}")
        return queue

    def unregister_frontend(self, context):
        q = self.frontend_queues.pop(context, None)
        log.info(f"[SESSION {self.task_id}] unregister_frontend: ctx={id(context)} removed (had_queue={q is not None}). listeners_left={len(self.frontend_queues)}")

    def get_backlog_count(self) -> int:
        return len(self.all_messages)

    async def mark_done(self):
        self.finished = True
        log.info(f"[SESSION {self.task_id}] mark_done: finished=True")


class TaskManager:
    """
    Менеджер сессий задач.
    Защищает создание сессий lock-ом, чтобы избежать race condition.
    """
    def __init__(self):
        self.tasks: Dict[int, TaskSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create_session(self, task_id: int) -> TaskSession:
        async with self._lock:
            session = self.tasks.get(task_id)
            if session is None:
                session = TaskSession(task_id)
                self.tasks[task_id] = session
                log.info(f"[TASK_MANAGER] Created new TaskSession for task_id={task_id}")
            else:
                log.debug(f"[TASK_MANAGER] Reusing existing TaskSession for task_id={task_id}")
            return session

    async def remove_session(self, task_id: int):
        async with self._lock:
            if task_id in self.tasks:
                del self.tasks[task_id]
                log.info(f"[TASK_MANAGER] Removed TaskSession for task_id={task_id}")
            else:
                log.debug(f"[TASK_MANAGER] remove_session: task_id={task_id} not found")


class FrontendStreamService(core_pb2_grpc.FrontendStreamServiceServicer):
    """Сервис для фронтенда: RunAlgorithm (server-streaming)."""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def RunAlgorithm(self, request, context):
        """
        При подключении фронта:
        - получаем единую сессию (get_or_create protected by lock)
        - регистрируем фронт (новая очередь)
        - отправляем backlog (все сохранённые сообщения)
        - продолжаем отдавать live-сообщения из очереди фронта с небольшим таймаутом
        - не удаляем сессию, пока алгоритм не прислал DONE и пока есть слушатели
        """
        task_id = request.task_id
        task_session = await self.task_manager.get_or_create_session(task_id)
        # register frontend and get its personal queue
        queue = task_session.register_frontend(context)

        log.info(f"[FRONT CONNECT] ctx={id(context)} task_id={task_id} listeners={len(task_session.frontend_queues)} backlog={task_session.get_backlog_count()}")

        try:
            # 1) Отдать backlog (все сохранённые сообщения)
            #    — это уже попало в личную очередь register_frontend, но мы явно пробежим и логируем
            #    чтобы убедиться, что backlog действительно отправляется.
            backlog_count = 0
            # Drain current items in queue that were backlog (but так как мы не помечаем что именно backlog,
            # будем просто отправлять из queue по очереди — это даст корректный порядок)
            while not queue.empty():
                msg = queue.get_nowait()
                backlog_count += 1
                log.info(f"[FRONT {task_id}] sending backlog msg response_id={msg.response_id} to ctx={id(context)}")
                yield msg

            log.info(f"[FRONT {task_id}] backlog send complete (sent={backlog_count}) to ctx={id(context)}; switching to live mode")

            # 2) Live loop: ждем новые сообщения, но используем небольшой timeout, чтобы корректно завершать поток
            while True:
                # Если задача завершена и в личной очереди нет элементов — завершаем поток
                if task_session.finished and queue.empty():
                    log.info(f"[FRONT {task_id}] finished and queue empty for ctx={id(context)} — closing stream")
                    break

                try:
                    # Ждём следующее сообщение из личной очереди с таймаутом
                    message = await asyncio.wait_for(queue.get(), timeout=0.5)
                    log.info(f"[FRONT {task_id}] sending live msg response_id={message.response_id} to ctx={id(context)}")
                    yield message
                except asyncio.TimeoutError:
                    # таймаут — проверим state и повторим цикл
                    continue

        except Exception as e:
            log.exception(f"[FRONT {task_id}] Exception in RunAlgorithm for ctx={id(context)}: {e}")
        finally:
            # Убираем фронта
            task_session.unregister_frontend(context)

            # Если задача завершена и нет слушателей — удаляем сессию
            if task_session.finished and not task_session.frontend_queues:
                log.info(f"[FRONT {task_id}] no listeners left and task finished — removing session")
                await self.task_manager.remove_session(task_id)
            else:
                log.info(f"[FRONT {task_id}] stream closed for ctx={id(context)}; listeners_left={len(task_session.frontend_queues)}")


class AlgorithmConnectionService(algorithm_pb2_grpc.AlgorithmConnectionServiceServicer):
    """Сервис для алгоритма: ConnectToCore (client-streaming)."""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def ConnectToCore(self, request_iterator, context):
        """
        Клиент (алгоритм) открывает stream_unary и шлёт последовательность GraphPartResponse.
        Мы находим/создаём TaskSession и кладём каждый message в историю и во фронт-очереди.
        """
        task_session: TaskSession | None = None

        async for message in request_iterator:
            # На первом сообщении создаём сессию (защищено lock-ом внутри)
            if task_session is None:
                task_session = await self.task_manager.get_or_create_session(message.task_id)
                task_session.algorithm_connected = True
                log.info(f"[ALG CONNECT] ctx_alg task_id={message.task_id} connected; listeners={len(task_session.frontend_queues)} backlog={task_session.get_backlog_count()}")

            # лог входящего сообщения
            log.info(f"[ALG MSG] task={message.task_id} response_id={message.response_id} status={message.status} type={message.WhichOneof('graph_part_type')}")

            # Добавляем сообщение в сессию (сохранение + push в queues)
            try:
                await task_session.add_message(message)
            except Exception as e:
                log.exception(f"[ALG MSG] Failed to add message task={message.task_id} response_id={message.response_id}: {e}")

            # Если пришёл DONE — отмечаем
            if message.status == common_pb2.ParseStatus.DONE:
                await task_session.mark_done()
                log.info(f"[ALG DONE] task={task_session.task_id} received DONE (response_id={message.response_id})")

        # Клиент-завершил отправку (ConnectToCore завершился)
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

    async def stop(self):
        log.info("CoreServer: остановка")
        await self.server.stop(0)


"""# ---- Standalone entry (optional) ----
if __name__ == "__main__":
    import asyncio
    server = CoreServer()
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("CoreServer: получен сигнал остановки")
        asyncio.run(server.stop())"""
