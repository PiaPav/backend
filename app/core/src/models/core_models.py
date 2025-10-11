from pydantic import BaseModel

from models.account_models import AccountData
from models.project_models import ProjectListDataLite


class HomePageData(BaseModel):
    user: AccountData
    projects: ProjectListDataLite
