from database.datamanager import DataManager
from endpoints.auth_endpoints import router as AuthRouter
from endpoints.core_endpoints import router as CoreRouter
from endpoints.account_endpoints import router as AccountRouter
from fastapi import FastAPI

app = FastAPI(title="PiaPav")


@app.on_event("startup")
async def startup_event():
    await DataManager.init_models()


@app.on_event("shutdown")
async def shutdown_event():
    await DataManager.close()


app.include_router(AuthRouter)
app.include_router(CoreRouter)
app.include_router(AccountRouter)
