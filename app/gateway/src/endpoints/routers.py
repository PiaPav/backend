from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.datamanager import DataManager
from endpoints.account_endpoints import router as AccountRouter
from endpoints.auth_endpoints import router as AuthRouter
from endpoints.core_endpoints import router as CoreRouter
from endpoints.project_endpoints import router as ProjectRouter
from exceptions.service_exception_middleware import init_handlers
from infrastructure.redis.redis_control import Redis
from services.manage.broker_manager import broker_repo_task


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Перед запуском
    await DataManager.init_models()
    await broker_repo_task.connect()
    yield

    # После завершения
    await DataManager.close()
    await broker_repo_task.close()


app = FastAPI(title="PiaPav", lifespan=lifespan, root_path="/api")

app.include_router(AuthRouter)
app.include_router(CoreRouter)
app.include_router(AccountRouter)
app.include_router(ProjectRouter)

init_handlers(app=app)

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/redis")
async def health_redis():
    try:
        pong = await Redis.check_redis()
        return {"status": "ok"} if pong else {"status": "fail"}
    except Exception as e:
        return {"status": "fail", "error": str(e)}
