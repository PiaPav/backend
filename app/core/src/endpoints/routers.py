from contextlib import asynccontextmanager

from fastapi import FastAPI

from database.datamanager import DataManager
from endpoints.account_endpoints import router as AccountRouter
from endpoints.auth_endpoints import router as AuthRouter
from endpoints.core_endpoints import router as CoreRouter
from endpoints.project_endpoints import router as ProjectRouter


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Перед запуском
    await DataManager.init_models()
    yield
    # После запуска
    await DataManager.close()


app = FastAPI(title="PiaPav", lifespan=lifespan)

app.include_router(AuthRouter)
app.include_router(CoreRouter)
app.include_router(AccountRouter)
app.include_router(ProjectRouter)
