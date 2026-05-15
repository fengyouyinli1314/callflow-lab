from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import cases, dashboard, reports, runs, tasks
from app.core.config import settings
from app.core.database import create_db_and_tables
from app.seed.sample_data import seed_sample_data


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    seed_sample_data()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health_check() -> dict:
    return {"status": "ok", "service": settings.app_name}


app.include_router(tasks.router)
app.include_router(cases.router)
app.include_router(runs.router)
app.include_router(reports.router)
app.include_router(dashboard.router)
