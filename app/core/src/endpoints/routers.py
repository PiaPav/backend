from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from multiprocessing import Process

from database.datamanager import DataManager
from exceptions.service_exception_middleware import init_handlers
from services.manage.broker_manager import broker_repo_task
from endpoints.account_endpoints import router as AccountRouter
from endpoints.auth_endpoints import router as AuthRouter
from endpoints.core_endpoints import router as CoreRouter
from endpoints.project_endpoints import router as ProjectRouter
from infrastructure.redis.redis_control import Redis
#from grpc_.grpc_process_runner import run_grpc

#grpc_process: Process | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    #global grpc_process
    # Перед запуском
    await DataManager.init_models()
    await broker_repo_task.connect()

    # запускаем gRPC в отдельном процессе
    #grpc_process = Process(target=run_grpc, daemon=True)
    #grpc_process.start()

    yield

    # После завершения
    await DataManager.close()
    await broker_repo_task.close()

    # остановка gRPC процесса
    #if grpc_process.is_alive():
    #    grpc_process.terminate()
    #    grpc_process.join()

app = FastAPI(title="PiaPav", lifespan=lifespan)

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
