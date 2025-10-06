from fastapi import HTTPException, status
from database.accounts import Account
from database.base import DataBaseEntityNotExists
from models.account_models import AccountFullData, AccountPatchData
from utils.logger import create_logger

log = create_logger("AccountService")


class AccountService:

    @staticmethod
    async def get_account_by_id(account_id: int) -> AccountFullData:
        try:
            account_bd = await Account.get_account_by_id(account_id)
            result = AccountFullData.model_validate(account_bd, from_attributes=True)
            return result

        except DataBaseEntityNotExists as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=e.message)

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

    @staticmethod
    async def patch_account_by_id(account_id: int, patch_data: AccountPatchData) -> AccountFullData:
        try:
            patch_result = await Account.patch_account_by_id(account_id, patch_data)
            result = AccountFullData.model_validate(patch_result, from_attributes=True)

            return result

        except DataBaseEntityNotExists as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=e.message)

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")