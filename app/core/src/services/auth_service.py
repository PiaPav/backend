from datetime import datetime, timedelta
import asyncio

import bcrypt
from jwt import PyJWT, DecodeError

from database.accounts import Account
from database.base import DataBaseEntityNotExists
from exceptions.service_exception_models import ConflictError, ErrorType, UnauthorizedError, \
    ServiceException
from models.account_models import AccountData, AccountCreateData, AccountEncodeData
from models.auth_models import LoginData, AuthResponseData, RefreshData, RegistrationData
from utils.config import CONFIG
from utils.logger import create_logger

JWT = PyJWT()

log = create_logger("AuthService")


class AuthService:
    @staticmethod
    async def registration(data: RegistrationData) -> AccountData:
        hashed_password = await AuthService.hash_password(data.password)
        try:
            account_exist = await Account.is_login_exists(data.login)
            if account_exist:
                log.error(f"Логин {data.login} занят")
                raise ConflictError(type=ErrorType.LOGIN_ALREADY_EXISTS, message=f"Логин {data.login} занят")
            account = await Account.create_account(create_data=AccountCreateData(name=data.name,
                                                                                 surname=data.surname,
                                                                                 login=data.login,
                                                                                 hashed_password=hashed_password))

            return AccountData.model_validate(account, from_attributes=True)

        except ServiceException as e:
            raise e

    @staticmethod
    async def verify_token(token: str) -> AccountEncodeData:
        try:
            result = await AuthService.check_token(token, CONFIG.auth.ACCESS_SECRET_KEY)
            return result
        except DecodeError:
            log.error(f"Неверный токен")
            raise UnauthorizedError(type=ErrorType.INVALID_TOKEN, message="Неверный токен")

        except ServiceException as e:
            raise e

    @staticmethod
    async def check_token(token: str, key: str) -> AccountEncodeData:
        user_data = await AuthService.decode_token(token, secret_key=key)
        if user_data.endDate < datetime.now():
            log.error("Токен access просрочен")
            raise UnauthorizedError(type=ErrorType.INVALID_TOKEN, message="Токен access просрочен")
        return user_data

    @staticmethod
    async def login(login_data: LoginData) -> AuthResponseData:
        try:
            bd_account = await Account.get_account_by_login(
                login_data.login)  # Может вызвать DataBaseEntityNotExists если нет логина
            await AuthService.verify_password(login_data.password, bd_account.hashed_password)

            data_to_token = AccountData(id=bd_account.id, name=bd_account.name, surname=bd_account.surname)
            access = await AuthService.encode_to_token(data_to_token, CONFIG.auth.ACCESS_TOKEN_EXPIRE_MINUTES,
                                                       secret_key=CONFIG.auth.ACCESS_SECRET_KEY)
            refresh = await AuthService.encode_to_token(data_to_token, CONFIG.auth.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60,
                                                        secret_key=CONFIG.auth.REFRESH_SECRET_KEY)

            return AuthResponseData(access_token=access,
                                    refresh_token=refresh,
                                    token_type="bearer")

        except DataBaseEntityNotExists as e:
            log.error(f"Неверный логин. Детали: {e.message}")
            raise UnauthorizedError(type=ErrorType.INVALID_LOGIN, message="Неверный логин")

        except ServiceException as e:
            raise e

    @staticmethod
    async def refresh(refresh_data: RefreshData) -> AuthResponseData:
        try:
            user_data = await AuthService.check_token(refresh_data.refresh_token, CONFIG.auth.REFRESH_SECRET_KEY)

            db_account = await Account.get_account_by_id(user_data.id)

            token_fields = (user_data.id, user_data.name, user_data.surname)
            db_fields = (db_account.id, db_account.name, db_account.surname)

            if token_fields != db_fields:
                raise UnauthorizedError(type=ErrorType.INVALID_TOKEN, message="Неверный токен")

            data_to_token = AccountData(id=user_data.id, name=user_data.name, surname=user_data.surname)
            access = await AuthService.encode_to_token(data_to_token, CONFIG.auth.ACCESS_TOKEN_EXPIRE_MINUTES,
                                                       secret_key=CONFIG.auth.ACCESS_SECRET_KEY)
            refresh = await AuthService.encode_to_token(data_to_token, CONFIG.auth.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60,
                                                        secret_key=CONFIG.auth.REFRESH_SECRET_KEY)
        except (DecodeError,
                DataBaseEntityNotExists) as e:  # ошибка декодирования | отсутствие аккаунта в бд (прислали поддельный токен)
            log.error(f"Неверный токен")
            raise UnauthorizedError(type=ErrorType.INVALID_TOKEN, message="Неверный токен",
                                    details={"raw_exception": e.message}) from e

        except ServiceException as e:
            raise e

        return AuthResponseData(access_token=access,
                                refresh_token=refresh,
                                token_type="bearer")

    @staticmethod
    async def encode_to_token(data: AccountData, expire: int, secret_key: str) -> str:
        """expire в минутах"""

        def _sync_encode():
            start_date = datetime.now()
            end_date = start_date + timedelta(minutes=expire)

            data_dict = data.model_dump()
            data_dict["startDate"] = start_date.isoformat()
            data_dict["endDate"] = end_date.isoformat()

            return JWT.encode(
                payload=data_dict,
                key=secret_key,
                algorithm=CONFIG.auth.ALGORITHM
            )

        return await asyncio.to_thread(_sync_encode)

    @staticmethod
    async def decode_token(token: str, secret_key: str) -> AccountEncodeData:

        def _sync_decode():
            result = JWT.decode(
                jwt=token,
                key=secret_key,
                algorithms=CONFIG.auth.ALGORITHM
            )
            return AccountEncodeData(
                result["id"],
                result["name"],
                result["surname"],
                datetime.fromisoformat(result["startDate"]),
                datetime.fromisoformat(result["endDate"])
            )

        return await asyncio.to_thread(_sync_decode)

    @staticmethod
    async def hash_password(password: str) -> str:

        def _sync_hash():
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
            return hashed.decode("utf-8")

        return await asyncio.to_thread(_sync_hash)

    @staticmethod
    async def verify_password(password: str, hashed_password: str) -> bool:

        def _sync_verify():
            return bcrypt.checkpw(
                password.encode("utf-8"),
                hashed_password.encode("utf-8")
            )

        result = await asyncio.to_thread(_sync_verify)

        if not result:
            log.error("Неверный пароль")
            raise UnauthorizedError(
                type=ErrorType.INVALID_PASSWORD,
                message="Неверный пароль"
            )

        return True