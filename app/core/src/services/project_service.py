from fastapi import HTTPException, status, UploadFile

from database.base import DataBaseEntityNotExists
from database.projects import Project
from models.account_models import AccountEncodeData
from models.project_models import ProjectData, ArchitectureModel, ProjectCreateData, ProjectPatchData, ProjectListData, \
    ProjectListDataLite, ProjectDataLite
from utils.logger import create_logger

from services.manage.broker_manager import broker_manager
from services.manage.object_manager import object_manager

log = create_logger("ProjectService")


class ProjectService:
    @staticmethod
    async def get_project_by_id(user_data: AccountEncodeData, project_id: int) -> ProjectData:
        try:
            project = await Project.get_project_by_id(project_id=project_id, account_id=user_data.id)

            architecture = ArchitectureModel(data=project.architecture)

            return ProjectData(id=project.id,
                               name=project.name,
                               description=project.description,
                               picture_url=project.picture_url,
                               architecture=architecture)

        except DataBaseEntityNotExists as e:
            log.error(f"У пользователя нет прав к проекту | Проект не существует. Детали: {e.message}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"У пользователя нет прав к проекту | Проект не существует")

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

    @staticmethod
    async def create_project(user_data: AccountEncodeData, create_data: ProjectCreateData,
                             file: UploadFile) -> ProjectData:
        try:

            project = await Project.create_project(create_data=create_data, author_id=user_data.id)

            architecture = ArchitectureModel(data=project.architecture)

            path = await object_manager.upload(fileobj=file, size = 1, path = user_data.name, arg = user_data.id, filename=file.filename) # заменить аргументы

            await broker_manager.publish(routing_key="tasks", message={"task_id": project.id, "project_path": path})

            return ProjectData(id=project.id,
                               name=project.name,
                               description=project.description,
                               picture_url=project.picture_url,
                               architecture=architecture)

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

            architecture = ArchitectureModel(data=project.architecture)

            return ProjectData(id=project.id,
                               name=project.name,
                               description=project.description,
                               picture_url=project.picture_url,
                               architecture=architecture)

        except DataBaseEntityNotExists as e:
            log.error(f"У пользователя нет прав к проекту | Проект не существует. Детали: {e.message}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"У пользователя нет прав к проекту | Проект не существует")

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"У пользователя нет прав к проекту | Проект не существует")

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

        except HTTPException:
            raise

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")
