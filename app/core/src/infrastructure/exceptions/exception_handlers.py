from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from infrastructure.exceptions.service_exception_models import ServiceException
from utils.logger import create_logger

log = create_logger("ExceptionHandlers")


def init_handlers(app: FastAPI):
    log.info("Инициализация обработчиков исключений начата")

    @app.exception_handler(ServiceException)
    async def service_exception_handler(request: Request, exc: ServiceException):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.error.model_dump(mode="json"),
        )

    log.info("Инициализация обработчиков исключений закончена")
