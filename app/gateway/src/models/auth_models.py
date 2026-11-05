from pydantic import BaseModel
from pydantic import Field


class AuthResponseData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class RefreshData(BaseModel):
    refresh_token: str


class LoginData(BaseModel):
    login: str
    password: str = Field(min_length=8, max_length=100)


class RegistrationData(BaseModel):
    name: str
    surname: str
    login: str
    password: str = Field(min_length=8, max_length=100)
