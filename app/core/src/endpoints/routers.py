from contextlib import asynccontextmanager

from fastapi import FastAPI

from database.datamanager import DataManager
from infrastructure.broker.manager import ConnectionBrokerManager
from infrastructure.broker.producer import Producer
from endpoints.account_endpoints import router as AccountRouter
from endpoints.auth_endpoints import router as AuthRouter
from endpoints.core_endpoints import router as CoreRouter
from endpoints.project_endpoints import router as ProjectRouter


broker_manager = ConnectionBrokerManager()
producer = Producer(broker_manager)



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Перед запуском
    await DataManager.init_models()
    # TODO добавить вызов connect для Rabbit
    await broker_manager.connect()
    yield
    # После запуска
    await DataManager.close()
    await broker_manager.close()


app = FastAPI(title="PiaPav", lifespan=lifespan)

app.include_router(AuthRouter)
app.include_router(CoreRouter)
app.include_router(AccountRouter)
app.include_router(ProjectRouter)
