from fastapi import HTTPException, status
from models.account_models import EncodeData, AccountData
from models.core_models import HomePageData
from services.account_service import AccountService
from utils.logger import create_logger

log = create_logger("CoreService")

class CoreService:

    @staticmethod
    async def get_homepage(user_data: EncodeData) -> HomePageData:
        try:
            account = await AccountService.get_account_by_id(user_data.id)
            account_data = AccountData.model_validate(account, from_attributes=True)
            hpd = HomePageData(user=account_data)

        except HTTPException:
            raise

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

        return hpd
