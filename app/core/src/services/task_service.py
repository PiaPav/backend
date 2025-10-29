from endpoints.routers import producer
from utils.config import CONFIG


class TaskService:
    queue_task_name = CONFIG.broker.queue_task
    queue_result_name = CONFIG.broker.queue_result

    async def add_task(self):
        pass

