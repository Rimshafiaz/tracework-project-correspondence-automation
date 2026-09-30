from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "unhealthy"]
    database: Literal["ok", "unavailable"]


def database_is_available() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


@router.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    if not database_is_available():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unhealthy", database="unavailable")
    return HealthResponse(status="ok", database="ok")

