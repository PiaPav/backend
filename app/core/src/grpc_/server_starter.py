import asyncio
from grpc_control.generated.shared import common_pb2

import grpc
from grpc_control.generated.api import algorithm_pb2_grpc


class AlgorithmConnectionService(algorithm_pb2_grpc.AlgorithmConnectionServiceServicer):
    async def ConnectToCore(self, request_iterator, context):
        async for msg in request_iterator:
            print("Получен кусок графа:", msg)
        return common_pb2.Empty()

async def serve():
    server = grpc.aio.server()
    algorithm_pb2_grpc.add_AlgorithmConnectionServiceServicer_to_server(
        AlgorithmConnectionService(), server
    )
    server.add_insecure_port("0.0.0.0:50051")
    await server.start()
    print("✅ gRPC сервер запущен на 50051")
    await server.wait_for_termination()

asyncio.run(serve())
