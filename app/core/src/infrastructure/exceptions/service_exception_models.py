from typing import Optional, Dict, Any

from pydantic import BaseModel


class ErrorDetails(BaseModel):
    type: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ServiceException(Exception):
    status_code: int = 500

    def __init__(self, *, type: str, message: str, details: Optional[dict] = None):
        self.error = ErrorDetails(type=type, message=message, details=details)
        super().__init__(message)

    @property
    def name(self) -> str:
        return self.__class__.__name__


class HTTPAccountNotFound(ServiceException):
    status_code = 404


class HTTPEmailSendCrash(ServiceException):
    status_code = 500


class HTTPEmailLinkError(ServiceException):
    status_code = 400


class HTTPEmailAlreadyTaken(ServiceException):
    status_code = 409


class HTTPEmailInvalidVerificationCode(ServiceException):
    status_code = 401


class HTTPLoginAlreadyExists(ServiceException):
    status_code = 409


class HTTPTokenInvalid401(ServiceException):
    status_code = 401


class HTTPAuthInvalid401(ServiceException):
    status_code = 401


class HTTPProjectNoRightsOrDontExists404(ServiceException):
    status_code = 404
