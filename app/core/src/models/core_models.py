from pydantic import BaseModel

from models.account_models import AccountData


class HomePageData(BaseModel):
    user: AccountData
