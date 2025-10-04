from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


class AccountData(BaseModel):
    id: int
    name: str
    surname: str


class AccountCreateData(BaseModel):
    name: str
    surname: str
    login: str
    hashed_password: str


@dataclass
class EncodeData:
    id: int
    name: str
    surname: str
    startDate: datetime
    endDate: datetime
