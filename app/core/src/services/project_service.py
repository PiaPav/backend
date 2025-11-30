from fastapi import HTTPException, status, UploadFile

from database.base import DataBaseEntityNotExists
from database.projects import Project
from infrastructure.exceptions.service_exception_models import NotFoundError, \
    ErrorType, ServiceException
from models.account_models import AccountEncodeData
from models.project_models import ProjectData, ArchitectureModel, ProjectCreateData, ProjectPatchData, \
    ProjectListDataLite, ProjectDataLite
from services.manage.broker_manager import broker_manager
from services.manage.object_manager import object_manager
from utils.logger import create_logger

log = create_logger("ProjectService")


class ProjectService:
    @staticmethod
    async def get_project_by_id(user_data: AccountEncodeData, project_id: int) -> ProjectData:
        try:
            project = await Project.get_project_by_id(project_id=project_id, account_id=user_data.id)

            architecture = ArchitectureModel(**project.architecture) if project.architecture else ArchitectureModel(
                requirements=None, endpoints=None, data=None)

            return ProjectData(id=project.id,
                               name=project.name,
                               description=project.description,
                               picture_url=project.picture_url,
                               architecture=architecture)

        except DataBaseEntityNotExists as e:
            log.error(f"У пользователя нет прав к проекту | Проект не существует. Детали: {e.message}")
            raise NotFoundError(type=ErrorType.PROJECT_NO_RIGHT_OR_NOT_FOUND,
                                message="У пользователя нет прав к проекту | Проект не существует")

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

    @staticmethod
    async def create_project(user_data: AccountEncodeData, create_data: ProjectCreateData,
                             file: UploadFile) -> ProjectData:
        try:
            path = await object_manager.upload_repozitory(file, file.filename, user_data.id)

            project = await Project.create_project(create_data=create_data, author_id=user_data.id, files_url=path)

            await broker_manager.publish(routing_key="tasks", message={"task_id": project.id, "project_path": path})

            architecture = ArchitectureModel(**project.architecture) if project.architecture else ArchitectureModel(
                requirements=None, endpoints=None, data=None)

            return ProjectData(id=project.id,
                               name=project.name,
                               description=project.description,
                               picture_url=project.picture_url,
                               architecture=architecture)

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

    @staticmethod
    async def update_project(user_data: AccountEncodeData, project_id: int,
                             patch_data: ProjectPatchData) -> ProjectData:
        try:
            project = await Project.patch_project_by_id(project_id=project_id, patch_data=patch_data,
                                                        account_id=user_data.id)

            architecture = ArchitectureModel(**project.architecture)

            return ProjectData(id=project.id,
                               name=project.name,
                               description=project.description,
                               picture_url=project.picture_url,
                               architecture=architecture)

        except DataBaseEntityNotExists as e:
            log.error(f"У пользователя нет прав к проекту | Проект не существует. Детали: {e.message}")
            raise NotFoundError(type=ErrorType.PROJECT_NO_RIGHT_OR_NOT_FOUND,
                                message="У пользователя нет прав к проекту | Проект не существует")

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

    @staticmethod
    async def delete_project(user_data: AccountEncodeData, project_id: int) -> None:
        try:
            await Project.delete_project(project_id, user_data.id)

            return

        except DataBaseEntityNotExists as e:
            log.error(f"У пользователя нет прав к проекту | Проект не существует. Детали: {e.message}")
            raise NotFoundError(type=ErrorType.PROJECT_NO_RIGHT_OR_NOT_FOUND,
                                message="У пользователя нет прав к проекту | Проект не существует")

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

    @staticmethod
    async def get_projects_by_account_id(user_data: AccountEncodeData) -> ProjectListDataLite:
        # Используются лайт версии данных проекта
        try:
            total, projects_db = await Project.get_project_list_by_account_id(account_id=user_data.id)
            projects_list = [ProjectDataLite.model_validate(project, from_attributes=True) for project in projects_db]
            return ProjectListDataLite(total=total, data=projects_list)

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")
