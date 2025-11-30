from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from exceptions.service_exception_descriptions import ERROR_DESCRIPTIONS
from exceptions.service_exception_models import ErrorType
from exceptions.service_exception_models import ServiceException
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


ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "description": "Код типа ошибки"
        },
        "message": {
            "type": "string",
            "description": "Сообщение ошибки"
        },
        "details": {
            "type": "object",
            "nullable": True,
            "description": "Дополнительные детали ошибки",
            "additionalProperties": True
        }
    },
    "required": ["type", "message"]
}


def get_error_responses(*error_types: ErrorType) -> Dict[int, Any]:
    """Генерирует словарь responses для передачи в декоратор роутера"""
    responses: Dict[int, Any] = {}
    grouped: dict[int, list[dict]] = {}

    for err_type in error_types:
        err_desc = ERROR_DESCRIPTIONS[err_type]
        status_code = err_desc["status_code"]
        grouped.setdefault(status_code, []).append(err_desc)

    for status_code, err_descs in grouped.items():
        if len(err_descs) == 1:
            err = err_descs[0]
            content = err["content"]
            responses[status_code] = {
                "description": content["message"],
                "content": {
                    "application/json": {
                        "schema": ERROR_SCHEMA,
                        "example": {
                            "type": content["type"].value,
                            "message": content["message"],
                            "details": None
                        }
                    }
                }
            }
        else:
            examples = {}
            for err in err_descs:
                content = err["content"]
                examples[content["type"].value] = {
                    "summary": content["message"],
                    "value": {
                        "type": content["type"].value,
                        "message": content["message"],
                        "details": None
                    }
                }

            responses[status_code] = {
                "description": "Возможные ошибки: " + " | ".join(
                    err["content"]["message"] for err in err_descs
                ),
                "content": {
                    "application/json": {
                        "schema": ERROR_SCHEMA,
                        "examples": examples
                    }
                }
            }

    return responses
