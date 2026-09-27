import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import get_settings
from .db import close_pool, get_pool, migrate
from .ingest.watcher import InboxWatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    applied = migrate()
    if applied:
        logging.info("applied migrations: %s", applied)
    get_pool()
    watcher = InboxWatcher()
    watcher.start()
    yield
    watcher.stop()
    close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="Second Brain", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
