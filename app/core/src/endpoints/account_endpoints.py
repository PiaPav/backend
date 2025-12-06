from fastapi import APIRouter, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from exceptions.service_exception_middleware import get_error_responses
from exceptions.service_exception_models import ErrorType
from infrastructure.profile.profile import profile_time
from models.account_models import AccountFullData, AccountPatchData, VerifyEmailType
from services.account_service import AccountService
from services.auth_service import AuthService
from utils.logger import create_logger

log = create_logger("AccountEndpoint")

router = APIRouter(prefix="/v1/account", tags=["Accounts"])

security = HTTPBearer()


@router.get("", status_code=status.HTTP_200_OK,
            responses=get_error_responses(ErrorType.INVALID_TOKEN),
            response_model=AccountFullData)
async def get_account(token: HTTPAuthorizationCredentials = Depends(security), auth_service: AuthService = Depends(),
                      service: AccountService = Depends()) -> AccountFullData:
    log.info(f"Получение данных аккаунта - начало")
    user = await auth_service.verify_token(token=token.credentials)
    result = await service.get_account_by_id(user.id)
    log.info(f"Получение данных аккаунта - конец")
    return result


@router.patch("", status_code=status.HTTP_200_OK,
              responses=get_error_responses(ErrorType.INVALID_TOKEN),
              response_model=AccountFullData)
async def patch_account(patch_data: AccountPatchData, token: HTTPAuthorizationCredentials = Depends(security),
                        auth_service: AuthService = Depends(), service: AccountService = Depends()) -> AccountFullData:
    log.info(f"Изменение данных аккаунта - начало")
    user = await auth_service.verify_token(token=token.credentials)
    result = await service.patch_account_by_id(user.id, patch_data)
    log.info(f"Изменение данных аккаунта - конец")
    return result

@router.delete("", status_code=status.HTTP_204_NO_CONTENT,
               responses=get_error_responses(ErrorType.INVALID_TOKEN))
async def delete_account(token: HTTPAuthorizationCredentials = Depends(security),
                         auth_service: AuthService = Depends(), service: AccountService = Depends()):
    log.info(f"Удаление аккаунта - начало")
    user = await auth_service.verify_token(token=token.credentials)
    await service.delete_account_by_id(user.id)
    log.info(f"Удаление аккаунта - конец")
    return


@router.post("/email", status_code=status.HTTP_200_OK,
             responses=get_error_responses(ErrorType.INVALID_TOKEN,
                                           ErrorType.EMAIL_SEND_CRASH,
                                           ErrorType.EMAIL_ALREADY_LINKED,
                                           ErrorType.EMAIL_ALREADY_TAKEN),
             response_model=bool)
async def link_email(email: str, token: HTTPAuthorizationCredentials = Depends(security),
                     auth_service: AuthService = Depends(), service: AccountService = Depends()) -> bool:
    log.info("Привязка email к аккаунту - начало")
    user = await auth_service.verify_token(token=token.credentials)
    result = await service.link_email(account_id=user.id, email=email)
    log.info("Привязка email к аккаунту - конец")
    return result


@router.post("/verification_email", status_code=status.HTTP_200_OK,
             responses=get_error_responses(ErrorType.INVALID_TOKEN,
                                           ErrorType.EMAIL_INVALID_CODE),
             response_model=bool)
async def verification_email(email: str, verify_type: VerifyEmailType, verification_code: int,
                             token: HTTPAuthorizationCredentials = Depends(security),
                             auth_service: AuthService = Depends(), service: AccountService = Depends()) -> bool:
    log.info(f"Подтверждение {verify_type.value} email к аккаунту - начало")
    user = await auth_service.verify_token(token=token.credentials)
    result = await service.verify_email(account_id=user.id, email=email, user_verification_code=verification_code,
                                        verify_type=verify_type)
    log.info(f"Подтверждение {verify_type.value} email к аккаунту - конец")
    return result


@router.delete("/email", status_code=status.HTTP_200_OK,
               responses=get_error_responses(ErrorType.INVALID_TOKEN,
                                             ErrorType.EMAIL_SEND_CRASH,
                                             ErrorType.EMAIL_DONT_LINKED),
               response_model=bool)
async def delete_email(token: HTTPAuthorizationCredentials = Depends(security), auth_service: AuthService = Depends(),
                       service: AccountService = Depends()) -> bool:
    log.info(f"Удаление почты у аккаунта - начало")
    user = await auth_service.verify_token(token=token.credentials)
    result = await service.delete_email(account_id=user.id)
    log.info(f"Удаление почты у аккаунта - конец")
    return result
