from fastapi import HTTPException, status

from database.accounts import Account
from database.base import DataBaseEntityNotExists
from infrastructure.email.email_service import EmailService, EmailServiceException
from exceptions.service_exception_models import ErrorDetails, NotFoundError, ErrorType, ClientError, InternalServerError, UnauthorizedError, ServiceException
from infrastructure.redis.redis_control import Redis
from infrastructure.security.security import Security
from models.account_models import AccountFullData, AccountPatchData, VerifyEmailType
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
            raise NotFoundError(type=ErrorType.ACCOUNT_NOT_FOUND, message="Аккаунт не найден",
                                details={"raw_exception": e.message}) from e

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"Непредвиденная ошибка: {type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            error_details = ErrorDetails(type=str(type(e)), message="Непредвиденная ошибка",
                                         details={"raw_exception": str(e)})
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_details.model_dump())

    @staticmethod
    async def patch_account_by_id(account_id: int, patch_data: AccountPatchData) -> AccountFullData:
        try:
            patch_result = await Account.patch_account_by_id(account_id, patch_data)
            result = AccountFullData.model_validate(patch_result, from_attributes=True)

            return result


        except DataBaseEntityNotExists as e:
            log.error(f"Аккаунт не найден. Детали: {e.message}")
            raise NotFoundError(type=ErrorType.ACCOUNT_NOT_FOUND, message="Аккаунт не найден",
                                details={"raw_exception": e.message}) from e

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"Непредвиденная ошибка: {type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            error_details = ErrorDetails(type=str(type(e)), message="Непредвиденная ошибка",
                                         details={"raw_exception": str(e)})
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_details.model_dump())

    @staticmethod
    async def link_email(account_id: int, email: str) -> bool:
        try:
            account_db = await Account.get_account_by_id(account_id)

            if account_db.email is not None:
                log.error(f"У аккаунта уже привязана почта")
                raise ClientError(type=ErrorType.EMAIL_ALREADY_LINKED, message="У аккаунта уже привязана почта")

            email_exists = await Account.is_email_exists(email=email)

            if email_exists:
                log.error(f"Почта {email} занята другим аккаунтом")
                raise ClientError(type=ErrorType.EMAIL_ALREADY_TAKEN, message="Почта занята")

            verification_code = await Security.generate_code(length=4)
            await Redis.set_verification_code(key=f"verification_code:LINK:{email}", code=verification_code,
                                              expire_seconds=EXPIRE_VERIFICATION_CODE_MINUTES * 60)

            result = await EmailService.send_email(email=email, username=account_db.name, code=verification_code,
                                                   expire_minutes=EXPIRE_VERIFICATION_CODE_MINUTES,
                                                   verify_type=VerifyEmailType.link)

            return result

        except DataBaseEntityNotExists as e:
            log.error(f"Аккаунт не найден. Детали: {e.message}")
            raise NotFoundError(type=ErrorType.ACCOUNT_NOT_FOUND, message="Аккаунт не найден",
                                details={"raw_exception": e.message}) from e

        except EmailServiceException as e:
            log.error(f"Ошибка при отправке письма. Детали: {e.message}")
            # TODO Нужен ли откат сохраненного в Redis кода верификации?
            raise InternalServerError(type=ErrorType.EMAIL_SEND_CRASH, message="Ошибка при отправке письма",
                                      details={"raw_exception": e.message}) from e

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"Непредвиденная ошибка: {type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок класса отправки писем, орм и бд
            error_details = ErrorDetails(type=str(type(e)), message="Непредвиденная ошибка",
                                         details={"raw_exception": str(e)})
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_details.model_dump())

    @staticmethod
    async def verify_email(account_id: int, email: str, user_verification_code: int,
                           verify_type: VerifyEmailType) -> bool:
        try:
            true_verification_code = await Redis.get_verification_code(
                key=f"verification_code:{verify_type.value}:{email}")

            if true_verification_code == user_verification_code:
                if verify_type is VerifyEmailType.link:
                    await Account.add_email_to_account(account_id=account_id, email=email)
                elif verify_type is VerifyEmailType.unlink:
                    await Account.delete_email_from_account(account_id=account_id)
                await Redis.delete_verification_code(key=f"verification_code:{verify_type.value}:{email}")
                return True

            log.error(f"Неверный код подтверждения для {email}")
            raise UnauthorizedError(type=ErrorType.EMAIL_INVALID_CODE, message=f"Неверный код подтверждения")

        except DataBaseEntityNotExists as e:
            log.error(f"Аккаунт не найден. Детали: {e.message}")
            raise NotFoundError(type=ErrorType.ACCOUNT_NOT_FOUND, message="Аккаунт не найден",
                                details={"raw_exception": e.message}) from e

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"Непредвиденная ошибка: {type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок класса отправки писем, орм и бд
            error_details = ErrorDetails(type=str(type(e)), message="Непредвиденная ошибка",
                                         details={"raw_exception": str(e)})
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_details.model_dump())

    @staticmethod
    async def delete_email(account_id: int) -> bool:
        try:
            account_db = await Account.get_account_by_id(account_id)

            if account_db.email is None:
                log.error(f"У аккаунта не привязана почта")
                raise ClientError(type=ErrorType.EMAIL_DONT_LINKED, message="У аккаунта не привязана почта")

            verification_code = await Security.generate_code(length=4)
            await Redis.set_verification_code(key=f"verification_code:UNLINK:{account_db.email}",
                                              code=verification_code,
                                              expire_seconds=EXPIRE_VERIFICATION_CODE_MINUTES * 60)

            result = await EmailService.send_email(email=account_db.email, username=account_db.name,
                                                   code=verification_code,
                                                   expire_minutes=EXPIRE_VERIFICATION_CODE_MINUTES,
                                                   verify_type=VerifyEmailType.unlink)

            return result

        except DataBaseEntityNotExists as e:
            log.error(f"Аккаунт не найден. Детали: {e.message}")
            raise NotFoundError(type=ErrorType.ACCOUNT_NOT_FOUND, message="Аккаунт не найден",
                                details={"raw_exception": e.message}) from e

        except EmailServiceException as e:
            log.error(f"Ошибка при отправке письма. Детали: {e.message}")
            raise InternalServerError(type=ErrorType.EMAIL_SEND_CRASH, message="Ошибка при отправке письма",
                                      details={"raw_exception": e.message}) from e

        except ServiceException as e:
            raise e

        except Exception as e:
            log.error(f"Непредвиденная ошибка: {type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок класса отправки писем, орм и бд
            error_details = ErrorDetails(type=str(type(e)), message="Непредвиденная ошибка",
                                         details={"raw_exception": str(e)})
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_details.model_dump())
