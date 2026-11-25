from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from exceptions.service_exception_middleware import get_error_responses
from exceptions.service_exception_models import ErrorType
from models.project_models import ProjectData, ProjectCreateData, ProjectListDataLite
from services.auth_service import AuthService
from services.project_service import ProjectService


security = HTTPBearer()
router = APIRouter(prefix="/v1/project", tags=["Project"])


@router.post("", status_code=status.HTTP_202_ACCEPTED,
             response_model=ProjectData,
             responses=get_error_responses(ErrorType.INVALID_TOKEN))
async def create_project(data: ProjectCreateData,
                         token: HTTPAuthorizationCredentials = Depends(security),
                         auth_service: AuthService = Depends(),
                         service: ProjectService = Depends()) -> ProjectData:
    user = await auth_service.verify_token(token.credentials)
    return await service.create_project(user_data=user, create_data=data)


@router.get("/{project_id}", status_code=status.HTTP_200_OK,
            response_model=ProjectData,
            responses=get_error_responses(ErrorType.INVALID_TOKEN,
                                          ErrorType.PROJECT_NO_RIGHT_OR_NOT_FOUND))
async def get_project(project_id: int,
                      token: HTTPAuthorizationCredentials = Depends(security),
                      auth_service: AuthService = Depends(),
                      service: ProjectService = Depends()) -> ProjectData:
    user = await auth_service.verify_token(token.credentials)
    return await service.get_project_by_id(user_data=user, project_id=project_id)


@router.get("", status_code=status.HTTP_200_OK,
            response_model=ProjectListDataLite,
            responses=get_error_responses(ErrorType.INVALID_TOKEN))
async def get_projects_list(token: HTTPAuthorizationCredentials = Depends(security),
                            auth_service: AuthService = Depends(),
                            service: ProjectService = Depends()) -> ProjectListDataLite:
    user = await auth_service.verify_token(token.credentials)
    return await service.get_projects_by_account_id(user_data=user)