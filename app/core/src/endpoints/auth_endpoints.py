from fastapi import APIRouter, status, Depends

from exceptions.service_exception_middleware import get_error_responses
from exceptions.service_exception_models import ErrorType
from models.account_models import AccountData
from models.auth_models import AuthResponseData, LoginData, RefreshData, RegistrationData
from services.auth_service import AuthService
from utils.logger import create_logger

log = create_logger("AuthEndpoint")

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


@router.post("/login", status_code=status.HTTP_200_OK,
             responses=get_error_responses(ErrorType.INVALID_LOGIN,
                                           ErrorType.INVALID_PASSWORD),
             response_model=AuthResponseData)
async def login(login_model: LoginData, service: AuthService = Depends()) -> AuthResponseData:
    log.info("Вход пользователя - начало")
    result = await service.login(login_data=login_model)
    log.info("Вход пользователя - конец")
    return result


@router.post("/refresh", status_code=status.HTTP_200_OK,
             responses=get_error_responses(ErrorType.INVALID_TOKEN),
             response_model=AuthResponseData)
async def refresh(refresh_model: RefreshData, service: AuthService = Depends()) -> AuthResponseData:
    log.info("Обновление токена - начало")
    result = await service.refresh(refresh_data=refresh_model)
    log.info("Обновление токена - конец")
    return result


@router.post("/registration", status_code=status.HTTP_200_OK,
             responses=get_error_responses(ErrorType.LOGIN_ALREADY_EXISTS),
             response_model=AccountData)
async def registration(data: RegistrationData, auth_service: AuthService = Depends()) -> AccountData:
    log.info("Регистрация аккаунта - начало")
    result = await auth_service.registration(data=data)
    log.info("Регистрация аккаунта - конец")
    return result
