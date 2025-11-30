from enum import Enum
from typing import Optional, Dict, Any

from pydantic import BaseModel


class ErrorType(Enum):
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"  # 404
    EMAIL_ALREADY_LINKED = "EMAIL_ALREADY_LINKED"  # 400
    EMAIL_ALREADY_TAKEN = "EMAIL_ALREADY_TAKEN"  # 400
    EMAIL_DONT_LINKED = "EMAIL_DONT_LINKED"  # 400
    EMAIL_SEND_CRASH = "EMAIL_SEND_CRASH"  # 500
    EMAIL_INVALID_CODE = "EMAIL_INVALID_CODE"  # 401
    LOGIN_ALREADY_EXISTS = "LOGIN_ALREADY_EXISTS"  # 409
    INVALID_TOKEN = "INVALID_TOKEN"  # 401
    INVALID_PASSWORD = "INVALID_PASSWORD"  # 401
    INVALID_LOGIN = "INVALID_LOGIN" # 401
    PROJECT_NO_RIGHT_OR_NOT_FOUND = "PROJECT_NO_RIGHT_OR_NOT_FOUND"  # 404


class ErrorDetails(BaseModel):
    type: ErrorType | str
    message: str
    details: Optional[Dict[str, Any]] = None


class ServiceException(Exception):
    status_code: int = 500

    def __init__(self, *, type: ErrorType | str, message: str, details: Optional[dict] = None):
        self.error = ErrorDetails(type=type, message=message, details=details)
        super().__init__(message)

    @property
    def name(self) -> str:
        return self.__class__.__name__


class ClientError(ServiceException):
    status_code = 400


class UnauthorizedError(ServiceException):
    status_code = 401


class NotFoundError(ServiceException):
    status_code = 404


class ConflictError(ServiceException):
    status_code = 409


class InternalServerError(ServiceException):
    status_code = 500
