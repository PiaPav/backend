import uvicorn

from endpoints.routers import app
from utils.config import CONFIG

if __name__ == "__main__":
    uvicorn.run(app, host=CONFIG.server.host, port=CONFIG.server.port)
