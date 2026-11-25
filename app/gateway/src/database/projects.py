from uuid import uuid4

from sqlalchemy import String, Text, ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column

from database.accounts import Account
from database.base import SQLBase, DataBaseEntityNotExists
from database.datamanager import DataManager
from models.project_models import ProjectCreateData, ProjectStatus


class Project(SQLBase):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey(Account.id, ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(250))
    repository_url: Mapped[str] = mapped_column(Text)
    branch: Mapped[str] = mapped_column(String(250))
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ProjectStatus.PENDING.value)
    correlation_id: Mapped[str] = mapped_column(String(36), unique=True)
    result_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @staticmethod
    async def create_project(create_data: ProjectCreateData, author_id: int) -> "Project":
        async with DataManager.session() as session:
            project = Project(
                author_id=author_id, name=create_data.name,
                repository_url=create_data.repository_url, branch=create_data.branch,
                status=ProjectStatus.PENDING.value, correlation_id=str(uuid4()),
            )
            session.add(project)
            await session.flush()
            return project

    @staticmethod
    async def get_project_by_id(project_id: int, account_id: int) -> "Project":
        async with DataManager.session() as session:
            project = await session.get(Project, project_id)
            if project is None or project.author_id != account_id:
                raise DataBaseEntityNotExists("Проект не найден")
            return project

    @staticmethod
    async def get_project_list_by_account_id(account_id: int) -> tuple[int, list["Project"]]:
        async with DataManager.session() as session:
            result = await session.execute(
                select(Project).where(Project.author_id == account_id)
            )
            projects = list(result.scalars().all())
            return len(projects), projects

    @staticmethod
    async def set_commit(project_id: int, commit_sha: str) -> None:
        async with DataManager.session() as session:
            project = await session.get(Project, project_id)
            if project is None:
                raise DataBaseEntityNotExists("Проект не найден")
            project.commit_sha = commit_sha

    @staticmethod
    async def set_result(correlation_id: str, result_uri: str) -> bool:
        async with DataManager.session() as session:
            result = await session.execute(
                select(Project).where(Project.correlation_id == correlation_id)
            )
            project = result.scalar_one_or_none()
            if project is None:
                return False

            project.result_uri = result_uri
            project.status = ProjectStatus.COMPLETED.value
            project.error = None
            return True

    @staticmethod
    async def set_failed(correlation_id: str, error: str) -> bool:
        async with DataManager.session() as session:
            result = await session.execute(
                select(Project).where(Project.correlation_id == correlation_id)
            )
            project = result.scalar_one_or_none()
            if project is None:
                return False

            if project.status != ProjectStatus.COMPLETED.value:
                project.status = ProjectStatus.FAILED.value
                project.error = error
            return True