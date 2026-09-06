from fastapi import APIRouter, Depends

from app.adapters.db.models import User
from app.api.deps import require_role

router = APIRouter()


@router.get("/admin/ping")
def admin_ping(user: User = Depends(require_role("admin"))):
    return {"ok": True, "role": "admin"}


@router.get("/designer/ping")
def designer_ping(user: User = Depends(require_role("designer"))):
    return {"ok": True, "role": "designer"}
