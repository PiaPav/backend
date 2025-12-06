from gunicorn.app.base import BaseApplication
from endpoints.routers import app
from utils.config import CONFIG


class StandaloneApplication(BaseApplication):
    """
    Класс для запуска Gunicorn через Python-код
    """
    def __init__(self, app, options=None):
        self.application = app
        self.options = options or {}
        super().__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items()
                  if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


if __name__ == "__main__":
    options = {
        "bind": f"{CONFIG.server.host}:{CONFIG.server.port}",
        "workers": {CONFIG.server.uvicorn_workers},
        "worker_class": "uvicorn.workers.UvicornWorker",
        "loglevel": "info",
        "timeout": 120,
        "keepalive": 5,
    }

    StandaloneApplication(app, options).run()
