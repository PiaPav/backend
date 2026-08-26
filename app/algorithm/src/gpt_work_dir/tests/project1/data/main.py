from gpt_work_dir.tests.project1.data.logic.logic import SomeClass as SC
from gpt_work_dir.tests.project1.data.models import CreateData, EnumTypes

if __name__ == "__main__":
    sc = SC()
    sc.create(create_data=CreateData("Имя", 5, EnumTypes.red))