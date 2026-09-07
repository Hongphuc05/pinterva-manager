from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import get_db, require_role
from app.application.kanban import list_kanban

router = APIRouter()


class KanbanCardOut(BaseModel):
    id: str
    external_order_id: str
    state: str
    product_name: str | None
    thumbnail_url: str | None
    job_type: str | None
    designer_name: str | None
    deadline_at_ext: str | None
    alerts: list[str]


class KanbanColumnOut(BaseModel):
    id: str
    title: str
    cards: list[KanbanCardOut]


class KanbanResponse(BaseModel):
    columns: list[KanbanColumnOut]


@router.get("/kanban", response_model=KanbanResponse)
def api_kanban(
    user: User = Depends(require_role("admin")), db: Session = Depends(get_db)
):
    return KanbanResponse(columns=list_kanban(db))
