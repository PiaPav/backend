from fastapi import APIRouter, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from models.account_models import AccountFullData, AccountPatchData
from services.account_service import AccountService
from services.auth_service import AuthService
from utils.logger import create_logger

log = create_logger("AccountEndpoint")

router = APIRouter(prefix="/v1/account", tags=["Accounts"])

security = HTTPBearer()


@router.get("", status_code=status.HTTP_200_OK, response_model=AccountFullData)
async def get_account(token: HTTPAuthorizationCredentials = Depends(security), auth_service: AuthService = Depends(),
                      service: AccountService = Depends()) -> AccountFullData:
    log.info(f"Получение данных аккаунта - начало")
    user = await auth_service.verify_token(token=token.credentials)
    result = await service.get_account_by_id(user.id)
    log.info(f"Получение данных аккаунта - конец")
    return result


@router.patch("", status_code=status.HTTP_200_OK, response_model=AccountFullData)
async def patch_account(patch_data: AccountPatchData, token: HTTPAuthorizationCredentials = Depends(security),
                        auth_service: AuthService = Depends(), service: AccountService = Depends()) -> AccountFullData:
    log.info(f"Изменение данных аккаунта - начало")
    user = await auth_service.verify_token(token=token.credentials)
    result = await service.patch_account_by_id(user.id, patch_data)
    log.info(f"Изменение данных аккаунта - конец")
    return result
