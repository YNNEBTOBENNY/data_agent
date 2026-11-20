from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401 确保模型注册
from .api import agent, auth, dashboard, datasources, query, research, semantic
from .db import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Data Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(datasources.router)
app.include_router(semantic.router)
app.include_router(query.router)
app.include_router(dashboard.router)
app.include_router(research.router)
app.include_router(agent.router)


@app.get("/health")
def health():
    return {"status": "ok"}
