# parse_service.py
import asyncio

from grpc_.algorithm_client import AlgorithmClient
import grpc_control.generated.shared.common_pb2 as common_pb2

from services.parser import EnhancedFunctionParser
from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("ParseService")

class ParseService:
    def __init__(self):
        self.client = AlgorithmClient(core_host=CONFIG.grpc.host, core_port=CONFIG.grpc.port)

    async def parse_project(self, task_id: int, project_path_s3: str):
        """Парсинг проекта через один стрим сообщений"""

        async def msg_generator():
            response_id = 1

            # ===== зависимости =====
            dependencies = await EnhancedFunctionParser.get_dependencies_s3(project_path_s3)
            log.info(f"Извлечены зависимости")
            for key, value in dependencies.items():
                yield common_pb2.GraphPartResponse(
                    task_id=task_id,
                    response_id=response_id,
                    status=common_pb2.ParseStatus.REQUIREMENTS,
                    graph_requirements=common_pb2.GraphPartRequirements(
                        total=len(value), requirements=value
                    )
                )
                log.info(f"Подготовлено сообщение {task_id} {response_id}")
                response_id += 1

            # ===== эндпоинты =====
            endpoints_raw = await EnhancedFunctionParser.extract_endpoints(project_path_s3)
            log.info(f"Извлечены эндпоинты")
            endpoints = {item["function"]: item["method"] + " " + item["path"] for item in endpoints_raw}
            yield common_pb2.GraphPartResponse(
                task_id=task_id,
                response_id=response_id,
                status=common_pb2.ParseStatus.ENDPOINTS,
                graph_endpoints=common_pb2.GraphPartEndpoints(
                    total=len(endpoints), endpoints=endpoints
                )
            )
            log.info(f"Подготовлено сообщение {task_id} {response_id}")
            response_id += 1

            # ===== архитектура =====
            async for parent, children in EnhancedFunctionParser.build_call_graph_s3(project_path_s3):
                yield common_pb2.GraphPartResponse(
                    task_id=task_id,
                    response_id=response_id,
                    status=common_pb2.ParseStatus.ARHITECTURE,
                    graph_architecture=common_pb2.GraphPartArchitecture(
                        parent=parent, children=children
                    )
                )
                log.info(f"Подготовлено сообщение {task_id} {response_id}")
                response_id += 1

            # ===== DONE =====
            yield common_pb2.GraphPartResponse(
                task_id=task_id,
                response_id=response_id,
                status=common_pb2.ParseStatus.DONE,
                graph_architecture=common_pb2.GraphPartArchitecture(parent="", children="")
            )
            log.info(f"Подготовлено сообщение {task_id} {response_id} — DONE")

        log.info(f"Начало парсинга задачи {task_id}")
        await self.client.stream(task_id, msg_generator())
        log.info(f"Конец парсинга задачи {task_id}")



async def run_parse_microservice(task_id, project_path_s3):
    service = ParseService()
    await service.parse_project(task_id, project_path_s3)

async def run():
    ps = ParseService()
    await ps.parse_project(987, r"")

if __name__ == "__main__":
    asyncio.run(run())
