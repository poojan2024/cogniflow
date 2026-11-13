"""Global search across the logged-in user's own data."""
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.schemas.search import SearchHit, SearchResponse
from app.services.search import SEARCH_TYPES, search_user_data

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def global_search(
    q: str = Query(min_length=2, max_length=100, description="Text to look for (at least 2 characters)"),
    types: Optional[str] = Query(default=None, description=f"Comma-separated subset of: {', '.join(SEARCH_TYPES)}"),
    limit: int = Query(default=10, ge=1, le=25, description="Maximum hits per type"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search text must have at least 2 characters.")
    selected = SEARCH_TYPES
    if types:
        selected = tuple(t.strip().lower() for t in types.split(",") if t.strip())
        unknown = [t for t in selected if t not in SEARCH_TYPES]
        if unknown or not selected:
            raise HTTPException(status_code=422, detail=f"Unknown search type. Allowed: {', '.join(SEARCH_TYPES)}")

    hits = [SearchHit(**asdict(h)) for h in search_user_data(db, current_user.id, query, selected, limit)]
    counts = {t: sum(1 for h in hits if h.type == t) for t in SEARCH_TYPES if t in selected}
    return SearchResponse(query=query, total=len(hits), counts=counts, results=hits)
