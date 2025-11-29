from typing import Optional

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from database.base import SQLBase, DataBaseEntityNotExists
from database.datamanager import DataManager
from models.account_models import AccountCreateData, AccountPatchData
from utils.logger import create_logger

log = create_logger("AccountDB")


class Account(SQLBase):
    """Аккаунты пользователей"""
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(250))
    surname: Mapped[str] = mapped_column(String(250))
    login: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(250), nullable=True, default=None)

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
    async def get_account_by_id(account_id: int, session: Optional[AsyncSession] = None) -> "Account":
        async with  DataManager.session(session) as session:
            result = await session.get(Account, account_id)

            if result is None:
                log.error(f"Аккаунт с id {account_id} не существует")
                raise DataBaseEntityNotExists(f"Аккаунт с id {account_id} не существует")

            return result

    @staticmethod
    async def get_account_by_login(account_login: str) -> "Account":
        async with DataManager.session() as session:
            result = await session.execute(select(Account).where(Account.login == account_login))
            result = result.scalar_one_or_none()

            if result is None:
                log.error(f"Аккаунт с логином {account_login} не существует")
                raise DataBaseEntityNotExists(f"Аккаунт с логином {account_login} не существует")

            return result

    @staticmethod
    async def is_login_exists(login: str) -> bool:
        async with DataManager.session() as session:
            result = await session.execute(
                select(Account.id).where(Account.login == login)
            )
            return result.scalar_one_or_none() is not None

    @staticmethod
    async def patch_account_by_id(account_id: int, patch_data: AccountPatchData) -> "Account":
        fields_to_patch = ["name", "surname"]
        async with DataManager.session() as session:
            account = await Account.get_account_by_id(account_id, session)

            for field, value in patch_data.model_dump().items():
                if value is not None and field in fields_to_patch:
                    setattr(account, field, value)

            await session.flush()
            return account

    @staticmethod
    async def add_email_to_account(account_id: int, email: str) -> "Account":
        async with DataManager.session() as session:
            account = await Account.get_account_by_id(account_id, session)

            account.email = email
            await session.flush()
            return account

    @staticmethod
    async def delete_email_from_account(account_id: int) -> "Account":
        async with DataManager.session() as session:
            account = await Account.get_account_by_id(account_id, session)

            account.email = None
            await session.flush()
            return account

    @staticmethod
    async def is_email_exists(email: str) -> bool:
        async with DataManager.session() as session:
            result = await session.execute(
                select(Account.id).where(Account.email == email)
            )
            return result.scalar_one_or_none() is not None

