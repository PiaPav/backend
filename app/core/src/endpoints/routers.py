from fastapi import FastAPI

from endpoints.auth_endpoints import router as AuthRouter
from database.datamanager import DataManager

app = FastAPI(title="PiaPav")


@app.on_event("startup")
async def startup_event():
    await DataManager.init_models()


@app.on_event("shutdown")
async def shutdown_event():
    await DataManager.close()


app.include_router(AuthRouter)
