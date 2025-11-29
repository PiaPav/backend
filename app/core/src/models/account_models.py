from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class AccountFullData(BaseModel):
    id: int
    name: str
    surname: str
    login: str


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
class AccountEncodeData:
    id: int
    name: str
    surname: str
    startDate: datetime
    endDate: datetime


class AccountPatchData(BaseModel):
    name: Optional[str]
    surname: Optional[str]


class VerifyEmailType(Enum):
    link = "LINK"
    unlink = "UNLINK"
