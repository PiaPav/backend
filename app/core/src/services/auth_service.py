from datetime import datetime, timedelta

import bcrypt
from database.accounts import Account
from fastapi import HTTPException, status
from jwt import PyJWT, DecodeError
from models.account_models import AccountData, AccountCreateData, EncodeData
from models.auth_models import LoginData, AuthResponseData, RefreshData, RegistrationData
from utils.config import CONFIG
from utils.logger import create_logger

JWT = PyJWT()

log = create_logger("AuthService")


class AuthService:
    @staticmethod
    async def registration(data: RegistrationData) -> AccountData:
        hashed_password = await AuthService.hash_password(password=data.password)
        try:
            account_exist = await Account.get_account_by_login(data.login)
            if account_exist is not None:
                log.error(f"Логин {data.login} занят")
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Логин {data.login} занят")
            account = await Account.create_account(create_data=AccountCreateData(name=data.name,
                                                                                 surname=data.surname,
                                                                                 login=data.login,
                                                                                 hashed_password=hashed_password))

        except HTTPException:
            raise

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

        return AccountData(id=account.id,
                           name=account.name,
                           surname=account.surname)

    @staticmethod
    async def verify_token(token: str) -> EncodeData:
        try:
            result = await AuthService.check_access_token(token)
            return result
        except DecodeError:
            log.error(f"Неверный токен")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

        except HTTPException:
            raise

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

    @staticmethod
    async def check_access_token(token: str):
        user_data = await AuthService.decode_token(token, secret_key=CONFIG.auth.ACCESS_SECRET_KEY)
        if user_data.endDate < datetime.now():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Токен access просрочен")
        return user_data

    @staticmethod
    async def login(login_data: LoginData) -> AuthResponseData:
        try:
            bd_account = await Account.get_account_by_login(login_data.login)
            log.info(f"Account {bd_account is None}")
            if bd_account is None:
                log.error(f"Неверный логин {login_data}")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Неверный логин")

            if not await AuthService.verify_password(login_data.password,
                                                     bd_account.hashed_password):
                log.error(f"Неверный пароль {login_data}")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Неверный пароль")

            data_to_token = AccountData(id=bd_account.id, name=bd_account.name, surname=bd_account.surname)
            access = await AuthService.encode_to_token(data_to_token, CONFIG.auth.ACCESS_TOKEN_EXPIRE_MINUTES,
                                                       secret_key=CONFIG.auth.ACCESS_SECRET_KEY)
            refresh = await AuthService.encode_to_token(data_to_token, CONFIG.auth.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60,
                                                        secret_key=CONFIG.auth.REFRESH_SECRET_KEY)

        except HTTPException:
            raise

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

        return AuthResponseData(access_token=access,
                                refresh_token=refresh,
                                token_type="bearer", )

    @staticmethod
    async def refresh(refresh_data: RefreshData) -> AuthResponseData:
        try:
            pass
            user_data = await AuthService.decode_token(refresh_data.refresh_token,
                                                       secret_key=CONFIG.auth.REFRESH_SECRET_KEY)
            if user_data.endDate < datetime.now():
                log.error(f"Токен просрочен")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Токен просрочен")

            db_account = await Account.get_account_by_id(user_data.id)

            token_fields = (user_data.id, user_data.name, user_data.surname)
            db_fields = (db_account.id, db_account.name, db_account.surname)

            if token_fields != db_fields:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

            data_to_token = AccountData(id=user_data.id, name=user_data.name, surname=user_data.surname)
            access = await AuthService.encode_to_token(data_to_token, CONFIG.auth.ACCESS_TOKEN_EXPIRE_MINUTES,
                                                       secret_key=CONFIG.auth.ACCESS_SECRET_KEY)
            refresh = await AuthService.encode_to_token(data_to_token, CONFIG.auth.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60,
                                                        secret_key=CONFIG.auth.REFRESH_SECRET_KEY)
        except DecodeError:
            log.error(f"Неверный токен")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

        except HTTPException:
            raise

        except Exception as e:
            log.error(f"{type(e)}, {str(e)}")
            # Пока заглушка, надо сделать проверки ошибок орм и бд
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{type(e)}, {str(e)}")

        return AuthResponseData(access_token=access,
                                refresh_token=refresh,
                                token_type="bearer")

    @staticmethod
    async def encode_to_token(data: AccountData, expire: int, secret_key: str) -> str:
        """expire в минутах"""
        start_date = datetime.now()
        end_date = start_date + timedelta(minutes=expire)
        data_dict = data.model_dump()
        data_dict["startDate"] = start_date.isoformat()
        data_dict["endDate"] = end_date.isoformat()
        result = JWT.encode(payload=data_dict, key=secret_key, algorithm=CONFIG.auth.ALGORITHM)
        return result

    @staticmethod
    async def decode_token(token: str, secret_key: str) -> EncodeData:
        result = JWT.decode(jwt=token, key=secret_key, algorithms=CONFIG.auth.ALGORITHM)
        return EncodeData(result["id"], result["name"], result["surname"],
                          datetime.fromisoformat(result["startDate"]), datetime.fromisoformat(result["endDate"]))

    @staticmethod
    async def hash_password(password: str) -> str:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    @staticmethod
    async def verify_password(password: str, hashed_password: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
