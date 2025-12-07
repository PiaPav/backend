import asyncio
from grpc_.core_server import CoreServer


async def main():
    server = CoreServer(host='0.0.0.0', port=50051)
    await server.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await server.stop()

if __name__ == "__main__":
    asyncio.run(main())
