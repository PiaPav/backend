from sqlalchemy import (Column, DateTime, func)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SQLBase(Base):
    """Базовый класс"""
    __abstract__ = True
    created_at = Column(DateTime, default=func.now(), nullable=False)


class DataBaseException(Exception):
    def __init__(self, message: str):
        self.message = "DataBaseException: " + message
        super().__init__(self.message)


class DataBaseEntityNotExists(DataBaseException):
    def __init__(self, message: str):
        self.message = "DataBaseEntityNotExists" + message
        super().__init__(self.message)
