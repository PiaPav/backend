import asyncio
import json
import os

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, unquote
from uuid import uuid4

from fastapi import HTTPException

from database.base import DataBaseEntityNotExists
from database.projects import Project
from exceptions.service_exception_models import NotFoundError, ErrorType
from infrastructure.git_repo_downloader import download_git_repo
from models.account_models import AccountEncodeData
from models.project_models import (
    ProjectData, ProjectCreateData, ProjectDataLite, ProjectListDataLite
)
from services.manage.broker_manager import broker_manager
from utils.logger import create_logger


log = create_logger("ProjectService")

SOURCES_ROOT = Path("/data/sources")
RESULTS_ROOT = Path("/data/results")


class ProjectService:

    @staticmethod
    async def create_project(user_data: AccountEncodeData,
                             create_data: ProjectCreateData) -> ProjectData:
        project = await Project.create_project(create_data=create_data, author_id=user_data.id)
        source_path = SOURCES_ROOT / project.correlation_id

        try:
            commit_sha = await download_git_repo(
                url=create_data.repository_url, branch=create_data.branch, path=source_path
            )

            await Project.set_commit(project.id, commit_sha)

            event_id = str(uuid4())
            event = {
                "event_id": event_id,
                "event_type": "parser.start.v1",
                "schema_version": 1,
                "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "correlation_id": project.correlation_id,
                "causation_id": event_id,
                "tenant_id": os.environ["TENANT_ID"],
                "producer": {"service": "gateway", "version": "1"},
                "payload": {
                    "source_uri": source_path.as_uri(),
                    "requested_graph": {
                        "schema_version": 1,
                        "parser_semantics_version": 7
                    }
                }
            }

            await broker_manager.publish(routing_key="parser.start.v1", event=event)

            log.info(f"Заявка {project.id} отправлена на анализ")

        except Exception as e:
            log.exception(f"Ошибка отправки проекта {project.id}")
            await Project.set_failed(project.correlation_id, str(e))
            raise HTTPException(status_code=502, detail=f"Не удалось отправить проект {project.id}") from e

        return await ProjectService.get_project_by_id(user_data, project.id)

    @staticmethod
    async def get_project_by_id(user_data: AccountEncodeData, project_id: int) -> ProjectData:
        try:
            project = await Project.get_project_by_id(project_id, user_data.id)

        except DataBaseEntityNotExists as e:
            raise NotFoundError(
                type=ErrorType.PROJECT_NO_RIGHT_OR_NOT_FOUND,
                message="Проект не найден или отсутствуют права доступа"
            ) from e

        data = ProjectData.model_validate(project)

        if project.result_uri:
            data.result = await asyncio.to_thread(
                ProjectService.read_result, project.result_uri
            )

        return data

    @staticmethod
    async def get_projects_by_account_id(user_data: AccountEncodeData) -> ProjectListDataLite:
        total, projects = await Project.get_project_list_by_account_id(user_data.id)
        return ProjectListDataLite(
            total=total,
            data=[ProjectDataLite.model_validate(project) for project in projects]
        )

    @staticmethod
    def read_result(uri: str) -> dict:
        parsed = urlsplit(uri)

        if parsed.scheme != "file" or parsed.netloc:
            raise ValueError("Unsupported result URI")

        path = Path(unquote(parsed.path)).resolve()

        if not path.is_relative_to(RESULTS_ROOT.resolve()):
            raise ValueError("Invalid result path")

        return json.loads(path.read_text(encoding="utf-8"))