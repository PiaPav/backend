from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from models.project_models import ProjectData, ProjectCreateData, ProjectPatchData
from services.auth_service import AuthService
from services.project_service import ProjectService
from utils.logger import create_logger

security = HTTPBearer()

log = create_logger("ProjectEndpoints")

router = APIRouter(prefix="/v1/project", tags=["Project"])


@router.get("/{project_id}", response_model=ProjectData)
async def get_project(project_id: int, token: HTTPAuthorizationCredentials = Depends(security),
                      auth_service: AuthService = Depends(), service: ProjectService = Depends()) -> ProjectData:
    log.info(f"Получение проекта {project_id} - начало")
    user = await auth_service.verify_token(token.credentials)
    result = await service.get_project_by_id(user_data=user, project_id=project_id)
    log.info(f"Получение проекта {project_id} - конец")
    return result


@router.post("/", response_model=ProjectData)
async def create_project(name: str, description: str, file: UploadFile = File(...),
                         token: HTTPAuthorizationCredentials = Depends(security),
                         auth_service: AuthService = Depends(), service: ProjectService = Depends()) -> ProjectData:
    log.info(f"Создание проекта - начало")
    user = await auth_service.verify_token(token.credentials)
    result = await service.create_project(user_data=user,
                                          create_data=ProjectCreateData(name=name, description=description), file=file)
    log.info(f"Создание проекта - конец")
    return result


@router.patch("/{project_id}", response_model=ProjectData)
async def patch_project(project_id: int, patch_data: ProjectPatchData,
                        token: HTTPAuthorizationCredentials = Depends(security), auth_service: AuthService = Depends(),
                        service: ProjectService = Depends()) -> ProjectData:
    log.info(f"Обновление проекта {project_id} - начало")
    user = await auth_service.verify_token(token.credentials)
    result = await service.update_project(user_data=user, project_id=project_id, patch_data=patch_data)
    log.info(f"Обновление проекта {project_id} - конец")
    return result
