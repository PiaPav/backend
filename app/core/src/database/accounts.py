from typing import Optional

from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column

from database.base import SQLBase
from database.datamanager import DataManager
from models.account_models import AccountCreateData


class Account(SQLBase):
    """Аккаунты пользователей"""
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(250))
    surname: Mapped[str] = mapped_column(String(250))
    login: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(200))

    @staticmethod
    async def create_account(create_data: AccountCreateData) -> "Account":
        async with DataManager.session() as session:
            account = Account(name=create_data.name,
                              surname=create_data.surname,
                              login=create_data.login,
                              hashed_password=create_data.hashed_password)
            session.add(account)
            return account

    @staticmethod
    async def get_account_by_id(account_id: int) -> Optional["Account"]:
        async with DataManager.session() as session:
            result = await session.get(Account, account_id)
            return result

    @staticmethod
    async def get_account_by_login(account_login: str) -> Optional["Account"]:
        async with DataManager.session() as session:
            result = await session.execute(select(Account).where(Account.login == account_login))
            return result.scalar_one_or_none()
