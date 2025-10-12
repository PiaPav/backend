from typing import Optional

from pydantic import BaseModel


# TODO Надо продумать в каком формате передавать архитектуру
class ArchitectureModel(BaseModel):
    data: Optional[dict]


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


# TODO продумать загрузку архива
class ProjectCreateData(BaseModel):
    name: str
    description: str


class ProjectPatchData(BaseModel):
    name: Optional[str]
    description: Optional[str]


class ProjectListData(BaseModel):
    total: int
    data: list[ProjectData]


class ProjectListDataLite(BaseModel):
    total: int
    data: list[ProjectDataLite]
