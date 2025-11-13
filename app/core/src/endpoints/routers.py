from contextlib import asynccontextmanager

from fastapi import FastAPI

from database.datamanager import DataManager
from grpc_.server_starter import start_grpc, stop_grpc
from infrastructure.broker.manager import ConnectionBrokerManager
from infrastructure.object_storage.object_storage_manager import ObjectStorageManager
from services.manage.broker_manager import BrokerManager
from services.manage.object_manager import ObjectManager

from endpoints.account_endpoints import router as AccountRouter
from endpoints.auth_endpoints import router as AuthRouter
from endpoints.core_endpoints import router as CoreRouter
from endpoints.project_endpoints import router as ProjectRouter


broker_repo_task = ConnectionBrokerManager(queue_name="tasks", key="tasks")
broker_manager = BrokerManager(broker_repo_task)

s3_repo = ObjectStorageManager()
object_manager = ObjectManager(s3_repo)


@asynccontextmanager
async def lifespan(app: FastAPI):

    # Перед запуском
    await DataManager.init_models()
    await broker_repo_task.connect()
    await start_grpc()
    yield

    # После запуска
    await DataManager.close()
    await broker_repo_task.close()
    await stop_grpc()


app = FastAPI(title="PiaPav", lifespan=lifespan)

app.include_router(AuthRouter)
app.include_router(CoreRouter)
app.include_router(AccountRouter)
app.include_router(ProjectRouter)
