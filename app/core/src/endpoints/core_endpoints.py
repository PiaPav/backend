from fastapi import APIRouter, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from models.core_models import HomePageData
from services.auth_service import AuthService
from services.core_service import CoreService
from utils.logger import create_logger

log = create_logger("CoreEndpoint")

router = APIRouter(prefix="/v1", tags=["Core"])

security = HTTPBearer()


@router.get("/home", status_code=status.HTTP_200_OK, response_model=HomePageData)
async def homepage(token: HTTPAuthorizationCredentials = Depends(security), auth_service: AuthService = Depends(),
                   service: CoreService = Depends()) -> HomePageData:
    log.info(f"Получение главной страницы - начало")
    user = await auth_service.verify_token(token=token.credentials)
    result = await service.get_homepage(user_data=user)
    log.info(f"Получение главной страницы - конец")
    return result
