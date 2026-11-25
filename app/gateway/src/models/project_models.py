from enum import StrEnum

from pydantic import BaseModel, Field, ConfigDict


class ProjectStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ProjectCreateData(BaseModel):
    name: str = Field(min_length=1, max_length=250)
    repository_url: str = Field(min_length=1, max_length=2048)
    branch: str = Field(min_length=1, max_length=250)


class ProjectDataLite(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    repository_url: str
    branch: str
    status: ProjectStatus


class ProjectData(ProjectDataLite):
    commit_sha: str | None = None
    result: dict | None = None
    error: str | None = None


class ProjectListDataLite(BaseModel):
    total: int
    data: list[ProjectDataLite]