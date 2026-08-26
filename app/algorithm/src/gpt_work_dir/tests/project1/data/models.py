from dataclasses import dataclass
from enum import Enum


class EnumTypes(Enum):
    red = "RED"
    blue = "BLUE"


@dataclass
class Cell:
    name: str
    count: int
    x: int
    y: int
    type: EnumTypes


@dataclass
class Data:
    points: list[Cell]
    score: int


@dataclass
class CreateData:
    name: str
    count: int
    type: EnumTypes
