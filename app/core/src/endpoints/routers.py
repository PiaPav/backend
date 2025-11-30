from contextlib import asynccontextmanager

from fastapi import FastAPI

from database.datamanager import DataManager
from endpoints.account_endpoints import router as AccountRouter
from endpoints.auth_endpoints import router as AuthRouter
from endpoints.core_endpoints import router as CoreRouter
from endpoints.project_endpoints import router as ProjectRouter
from grpc_.server_starter import start_grpc, stop_grpc
from exceptions.service_exception_middleware import init_handlers
from services.manage.broker_manager import broker_repo_task


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

init_handlers(app=app)

app.include_router(AuthRouter)
app.include_router(CoreRouter)
app.include_router(AccountRouter)
app.include_router(ProjectRouter)


@app.get("/health")
async def health():
    return {"status": "ok"}
