from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.integrations import router as integrations_router
from app.api.lineage import router as lineage_router
from app.api.projects import router as projects_router
from app.api.project_resolution_reviews import router as review_router
from app.api.reply_drafts import router as reply_drafts_router
from app.api.reviews import router as consolidated_review_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(health_router)
app.include_router(review_router)
app.include_router(consolidated_review_router)
app.include_router(projects_router)
app.include_router(lineage_router)
app.include_router(integrations_router)
app.include_router(reply_drafts_router)
