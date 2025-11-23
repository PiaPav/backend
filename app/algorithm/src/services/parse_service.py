#parse_service.py
import asyncio

from grpc_.algorithm_client import AlgorithmClient
import grpc_control.generated.shared.common_pb2 as common_pb2

from services.parser import EnhancedFunctionParser
from utils.logger import create_logger

log = create_logger("ParseService")

class ParseService:
    def __init__(self):
        self.client = AlgorithmClient()

    async def parse_project(self, task_id: int, project_path: str):
        """Парсинг проекта"""
        log.info(f"Начало парсинга задачи {task_id}")
        response_id = 1
        # Извлечение зависимостей
        dependencies = EnhancedFunctionParser.get_dependencies(project_path)
        # print(dependencies)
        log.info(f"Извлечены зависимости")
        for key, value in dependencies.items():
            msg = common_pb2.GraphPartResponse(task_id=task_id, response_id=1, status=common_pb2.ParseStatus.REQUIREMENTS,
                                               graph_requirements=common_pb2.GraphPartRequirements(
                                                   total=len(value), requirements=value))
            # print(msg)
            log.info(f"Отправлено сообщение {msg}")
            response_id += 1
            await self.client.send(task_id, msg)

        # Извлечение эндпоинтов
        endpoints_raw = EnhancedFunctionParser.extract_endpoints(project_path)
        log.info(f"Извлечены эндпоинты")
        endpoints = {}
        for item in endpoints_raw:
            endpoints[item["function"]] = item["method"] + " " + item["path"]
        msg = common_pb2.GraphPartResponse(task_id=task_id, response_id=2, status=common_pb2.ParseStatus.ENDPOINTS,
                                           graph_endpoints=common_pb2.GraphPartEndpoints(
                                               total=len(endpoints), endpoints=endpoints))
        # print(msg)
        log.info(f"Отправлено сообщение {msg}")
        response_id += 1
        await self.client.send(task_id, msg)

        # Извлечение архитектуры
        async for parent, children in EnhancedFunctionParser.build_call_graph(project_path):
            msg = common_pb2.GraphPartResponse(task_id=task_id, response_id=response_id, status=common_pb2.ParseStatus.ARHITECTURE,
                                               graph_architecture=common_pb2.GraphPartArchitecture(
                                               parent=parent, children=children))
            # print(msg)
            log.info(f"Отправлено сообщение {msg}")
            response_id += 1
            await self.client.send(task_id, msg)
        # Отправка окончания
        msg = common_pb2.GraphPartResponse(task_id=task_id, response_id=response_id, status=common_pb2.ParseStatus.DONE,
                                               graph_architecture=common_pb2.GraphPartArchitecture(
                                               parent="", children=""))
        log.info(f"Отправлено сообщение {msg}")
        await self.client.send(task_id, msg)
        log.info(f"Конец парсинга задачи {task_id}")

async def run_parse_microservice(task_id, project_path):
    service = ParseService()
    await service.parse_project(task_id, project_path)

# Тесты
async def run():
    ps = ParseService()
    await ps.parse_project(987, r"")

if __name__ == "__main__":
    asyncio.run(run())


