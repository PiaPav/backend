# grpc_process_runner.py
import asyncio
import multiprocessing
from grpc_.server_starter import start_grpc, stop_grpc

def run_grpc():
    """Запуск gRPC в отдельном процессе"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_grpc())
        loop.run_forever()
    except KeyboardInterrupt:
        loop.run_until_complete(stop_grpc())
    finally:
        loop.close()
