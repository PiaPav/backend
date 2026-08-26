from gpt_work_dir.tests.project1.data.logic.generator import get_random_x_y
from gpt_work_dir.tests.project1.data.interface import SomeInterface
from gpt_work_dir.tests.project1.data.models import CreateData, Data, Cell


class SomeClass(SomeInterface):

    def __init__(self):
        self.data: Data = Data([], 0)

    def create(self, create_data: CreateData):
        xy = get_random_x_y()
        cell = Cell(name=create_data.name,
                    count=create_data.count,
                    type=create_data.type,
                    x=xy[0],
                    y=xy[1])
        self.data.points.append(cell)

    def clear(self):
        self.data = Data([], 0)