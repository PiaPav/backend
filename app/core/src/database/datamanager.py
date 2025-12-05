from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from typing import TypeVar

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from database.base import Base
from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("DatabaseManager")

db_url = f"postgresql+asyncpg://{CONFIG.db.user}:{CONFIG.db.password}@{CONFIG.db.host}:{CONFIG.db.port}/{CONFIG.db.name}"

T = TypeVar('T')


class DatabaseManager:
    def __init__(self, url: str, echo: bool = False):
        self.engine = create_async_engine(url,
                                          echo=echo,
                                          future=True,
                                          pool_size=20,         # Максимум соединений в пуле
                                          max_overflow=10)     # Дополнительные соединения сверх pool_size
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
            autoflush=False
        )

    async def init_models(self, drop: bool = False, model_name: str = None):
        log.info(f"Start init models")
        async with self.engine.begin() as conn:
            if drop:
                if model_name:
                    target_table = Base.metadata.tables.get(model_name)
                    if target_table is not None:
                        await conn.run_sync(target_table.drop)
                    else:
                        raise ValueError(f"Model '{model_name}' not found in metadata")
                else:
                    await conn.run_sync(Base.metadata.drop_all)

            if model_name:
                target_table = Base.metadata.tables.get(model_name)
                if target_table is not None:
                    await conn.run_sync(target_table.create)
                else:
                    raise ValueError(f"Model '{model_name}' not found in metadata")
            else:
                await conn.run_sync(Base.metadata.create_all)
        log.info(f"End init models")

    @asynccontextmanager
    async def session(self, exist_session: Optional[AsyncSession] = None) -> AsyncGenerator[AsyncSession, None]:
        if exist_session is not None:
            yield exist_session
        else:
            async with self.session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()

    async def close(self):
        await self.engine.dispose()


DataManager = DatabaseManager(db_url, echo=CONFIG.db.echo)


async def init_db():
    await DataManager.init_models()
