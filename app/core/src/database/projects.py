from typing import Optional

from sqlalchemy import String, JSON, Text, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from database.accounts import Account
from database.base import SQLBase, DataBaseEntityNotExists
from database.datamanager import DataManager
from models.project_models import ProjectCreateData, ProjectPatchData
from utils.logger import create_logger

log = create_logger("ProjectDB")


class Project(SQLBase):
    """Проекты пользователей"""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey(Account.id))
    name: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text)
    picture_url: Mapped[str] = mapped_column(String(250), default="")
    architecture: Mapped[dict] = mapped_column(JSON, nullable=True)
    files_url = Mapped[str] = mapped_column(String(300), )

    @staticmethod
    async def create_project(create_data: ProjectCreateData, author_id: int) -> "Project":
        async with DataManager.session() as session:
            project = Project(author_id=author_id,
                              name=create_data.name,
                              description=create_data.description)
            session.add(project)
            return project

    @staticmethod
    async def get_project_by_id(project_id: int, account_id: int, session: Optional[AsyncSession] = None) -> "Project":
        async with  DataManager.session(session) as session:
            result = await session.get(Project, project_id)

            if result is None or result.author_id != account_id:
                log.error(f"Проект с id {project_id} не найден или не существует")
                raise DataBaseEntityNotExists(f"Проект с id {project_id} не найден или не существует")

            return result

    @staticmethod
    async def patch_project_by_id(project_id: int, patch_data: ProjectPatchData, account_id: int) -> "Project":
        async with DataManager.session() as session:
            project = await Project.get_project_by_id(project_id, account_id, session)

            for field, value in patch_data.model_dump().items():
                if value is not None:
                    setattr(project, field, value)

            await session.flush()
            return project

    @staticmethod
    async def get_project_list_by_account_id(account_id: int) -> tuple[int, list["Project"]]:
        async with DataManager.session() as session:
            stmt = select(Project).where(Project.author_id == account_id)
            result = await session.execute(stmt)
            projects = result.scalars().all()
            total = len(projects)
            return total, projects
