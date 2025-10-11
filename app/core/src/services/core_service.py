from fastapi import HTTPException, status

from database.projects import Project
from models.account_models import AccountEncodeData, AccountData
from models.core_models import HomePageData
from models.project_models import ProjectListDataLite, ProjectDataLite
from services.account_service import AccountService
from utils.logger import create_logger

log = create_logger("CoreService")


class CoreService:

    @staticmethod
    async def get_homepage(user_data: AccountEncodeData) -> HomePageData:
        # Используются лайт версии данных проекта
        try:
            account = await AccountService.get_account_by_id(user_data.id)
            account_data = AccountData.model_validate(account, from_attributes=True)

            total, projects_db = await Project.get_project_list_by_account_id(account_id=user_data.id)
            projects_list = [ProjectDataLite.model_validate(project, from_attributes=True) for project in projects_db]
            projects_data = ProjectListDataLite(total=total, data=projects_list)

            hpd = HomePageData(user=account_data, projects=projects_data)

            return hpd

        except HTTPException:
            raise

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")
