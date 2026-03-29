import json
import time
from parser import analyze_code
from services.experimental_parser.graph_merger import GraphMerger
from services.experimental_parser.utils import create_project_index
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent

CORE_DIR = (CURRENT_DIR / "../../../../core").resolve()

project_files = [r'src\main.py',
             r'src\database\accounts.py',
             r'src\database\base.py',
             r'src\database\datamanager.py',
             r'src\database\projects.py',
             r'src\endpoints\account_endpoints.py',
             r'src\endpoints\auth_endpoints.py',
             r'src\endpoints\core_endpoints.py',
             r'src\endpoints\project_endpoints.py',
             r'src\endpoints\routers.py',
             r'src\exceptions\service_exception_descriptions.py',
             r'src\exceptions\service_exception_middleware.py',
             r'src\exceptions\service_exception_models.py',
             r'src\infrastructure\broker\interface.py',
             r'src\infrastructure\broker\manager.py',
             r'src\infrastructure\broker\producer.py',
             r'src\infrastructure\email\email_service.py',
             r'src\infrastructure\object_storage\interface.py',
             r'src\infrastructure\object_storage\object_storage_manager.py',
             r'src\infrastructure\profile\profile.py',
             r'src\infrastructure\redis\interface.py',
             r'src\infrastructure\redis\redis_control.py',
             r'src\infrastructure\security\security.py',
             r'src\models\account_models.py',
             r'src\models\auth_models.py',
             r'src\models\core_models.py',
             r'src\models\project_models.py',
             r'src\services\account_service.py',
             r'src\services\auth_service.py',
             r'src\services\core_service.py',
             r'src\services\project_service.py',
             r'src\services\manage\broker_manager.py',
             r'src\services\manage\object_manager.py',
             r'src\utils\config.py',
             r'src\utils\logger.py']


def _norm(obj):
    """Рекурсивная нормализация: сортирует списки для нечувствительного к порядку сравнения."""
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        # Сортируем: сначала приводим элементы к строке для ключа, потом сортируем
        return sorted((_norm(item) for item in obj), key=lambda x: json.dumps(x, sort_keys=True))
    return obj


def test_graph_matches_reference():
    """
    Шаблон теста: сравнивает результат парсера с эталоном.

    Параметры передаются извне (conftest.py или pytest.parametrize).
    """
    graphs = []

    reference_path = r"reference.json"

    total_start = time.perf_counter()

    # Запускаем парсер
    for filename in project_files:
        with open(CORE_DIR / filename, "r", encoding="utf-8") as f:
            code = f.read()

        result = analyze_code(code, project_files, filename)

        graphs.append(result)

    project_modules = create_project_index(project_files)
    merger = GraphMerger(project_modules=project_modules)

    full_graph = merger.merge(graphs, group_by_file=True)

    total_end = time.perf_counter()
    print(f"TOTAL TIME: {total_end - total_start}")

    with open("new.json", "w") as f:
        f.write(merger.export_grouped(format="json"))

    # Загружаем эталон
    with open(reference_path, 'r', encoding='utf-8') as f:
        reference = json.load(f)

    # Сравниваем нормализованные структуры
    assert _norm(full_graph) == _norm(reference), (
        "Graph mismatch!\n"
        f"Expected: {json.dumps(_norm(reference), indent=2, ensure_ascii=False)[:500]}...\n"
        f"Got:      {json.dumps(_norm(full_graph), indent=2, ensure_ascii=False)[:500]}..."
    )

def test_10():
    for _ in range(10):
        test_graph_matches_reference()