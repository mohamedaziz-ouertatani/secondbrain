import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .admin.backup import BackupScheduler
from .admin.sync import AutoSync, runner
from .api.admin import router as admin_router
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
    autosync = AutoSync()
    autosync.start()
    backups = BackupScheduler()
    backups.start()
    yield
    backups.stop()
    autosync.stop()
    runner.cancel()  # a running sync must not outlive the backend
    watcher.stop()
    close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="Second Brain", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(admin_router)
    return app


app = create_app()
