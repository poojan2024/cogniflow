from typing import Dict, List, Optional

from pydantic import BaseModel


class SearchHit(BaseModel):
    type: str  # activities | documents | extracted | notes | tasks | expenses
    id: int
    title: str
    snippet: str
    activity_id: Optional[int] = None
    activity_title: Optional[str] = None
    document_id: Optional[int] = None  # set for documents and extracted-information hits


class SearchResponse(BaseModel):
    query: str
    total: int  # number of hits returned (at most `limit` per type)
    counts: Dict[str, int]  # hits returned per type
    results: List[SearchHit]
