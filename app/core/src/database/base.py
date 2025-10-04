from sqlalchemy import (Column, DateTime, func)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SQLBase(Base):
    """Базовый класс"""
    __abstract__ = True
    created_at = Column(DateTime, default=func.now(), nullable=False)
