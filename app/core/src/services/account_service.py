from fastapi import HTTPException, status

from database.accounts import Account
from database.base import DataBaseEntityNotExists
from infrastructure.redis.redis_control import Redis
from infrastructure.security.security import Security
from models.account_models import AccountFullData, AccountPatchData
from services.email_service import EmailService
from utils.logger import create_logger

log = create_logger("AccountService")

EXPIRE_VERIFICATION_CODE_MINUTES = 5


class AccountService:

    @staticmethod
    async def get_account_by_id(account_id: int) -> AccountFullData:
        try:
            account_db = await Account.get_account_by_id(account_id)
            result = AccountFullData.model_validate(account_db, from_attributes=True)
            return result

        except DataBaseEntityNotExists as e:
            log.error(f"Аккаунт не найден. Детали: {e.message}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Аккаунт не найден")

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
            log.error(f"Аккаунт не найден. Детали: {e.message}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Аккаунт не найден")

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")
    
    @staticmethod
    async def link_email(account_id: int, email: str) -> bool:
        try:
            account_db = await Account.get_account_by_id(account_id)

            verification_code = await Security.generate_code(length=4)
            await Redis.set_verification_code(key=f"verification_code:{email}", code=verification_code, expire_seconds=EXPIRE_VERIFICATION_CODE_MINUTES*60)

            result = await EmailService.send_email(email=email, username=account_db.name, code=verification_code, expire_minutes=EXPIRE_VERIFICATION_CODE_MINUTES)

            return result

        except DataBaseEntityNotExists as e:
            log.error(f"Аккаунт не найден. Детали: {e.message}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Аккаунт не найден")

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок класса отправки писем, орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

    @staticmethod
    async def verify_email(account_id: int, email: str, user_verification_code: int) -> bool:
        try:
            true_verification_code = await Redis.get_verification_code(key=f"verification_code:{email}")
            log.info(f"True: {true_verification_code}, user: {user_verification_code}")

            if true_verification_code == user_verification_code:
                await Account.add_email_to_account(account_id=account_id, email=email)
                await Redis.delete_verification_code(key=f"verification_code:{email}")
                return True

            log.error(f"Неверный код подтверждения для {email}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Неверный код подтверждения")

        except DataBaseEntityNotExists as e:
            log.error(f"Аккаунт не найден. Детали: {e.message}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Аккаунт не найден")

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок класса отправки писем, орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")


            
