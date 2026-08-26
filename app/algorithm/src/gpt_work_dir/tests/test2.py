from gpt_work_dir.parser.logic.errors import SourceSyntaxError
from gpt_work_dir.parser.logic.main import starter

import json

from pathlib import Path

project_path = Path(r"C:\Users\Red0c\PycharmProjects\PiaPav\backend\app\core\src")


result = starter(project_path)
print(json.dumps(result, indent=2))
