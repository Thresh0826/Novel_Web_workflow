"""Run only the local workbench without configuring or invoking LLMs."""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from .api.local_workbench import router

app = FastAPI(title="小说协作工作台 · 本地演示")
app.include_router(router)

@app.get("/")
def home():
    return RedirectResponse("/workbench")
