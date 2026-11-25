from contextlib import asynccontextmanager

from fastapi import FastAPI

from database.datamanager import DataManager
from endpoints.auth_endpoints import router as AuthRouter
from endpoints.project_endpoints import router as ProjectRouter
from exceptions.service_exception_middleware import init_handlers
from infrastructure.broker_adapters import (
    declare_topology, consume_result, consume_error
)
from services.manage.broker_manager import broker_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await DataManager.init_models()

        await broker_manager.connect(prefetch_count=1)
        await declare_topology(broker_manager)

        await broker_manager.consume(
            queue_name="results", routing_key="harness.completed.v1", handler=consume_result
        )

        await broker_manager.consume(
            queue_name="errors", routing_key="*.failed.v1", handler=consume_error
        )

        yield

    finally:
        await broker_manager.close()
        await DataManager.close()


app = FastAPI(title="PiaPav", lifespan=lifespan)

app.include_router(AuthRouter)
app.include_router(ProjectRouter)

init_handlers(app=app)


@app.get("/health")
async def health():
    return {"status": "ok"}