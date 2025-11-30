from typing import Optional

from pydantic import BaseModel


# TODO Надо продумать в каком формате передавать архитектуру
class ArchitectureModel(BaseModel):
    requirements: Optional[list[str]] = None
    endpoints: Optional[list[dict]] = None
    data: Optional[dict] = None
    """0, 1, 2, 3, 4
    {0: [{3, 2}, (150, 200)], 
     1: {2}, 
     2: {0, 1, 5}}"""


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
    name: Optional[str] = None
    description: Optional[str] = None
    architecture: Optional[ArchitectureModel] = None


class ProjectListData(BaseModel):
    total: int
    data: list[ProjectData]


class ProjectListDataLite(BaseModel):
    total: int
    data: list[ProjectDataLite]
