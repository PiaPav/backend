from typing import Optional

from pydantic import BaseModel


class ArchitectureModel(BaseModel):
    requirements: Optional[list[str]] = None
    endpoints: Optional[list[dict]] = None
    data: Optional[dict] = None


class ProjectDataLite(BaseModel):
    id: int
    name: str
    description: str
    picture_url: str


class ProjectData(BaseModel):
    id: int
    name: str
    description: str
    picture_url: str
    architecture: ArchitectureModel


class ProjectCreateData(BaseModel):
    name: str
    description: str


class ProjectPatchData(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    architecture: Optional[ArchitectureModel] = None


class ProjectListData(BaseModel):
    total: int
    data: list[ProjectData]


class ProjectListDataLite(BaseModel):
    total: int
    data: list[ProjectDataLite]
