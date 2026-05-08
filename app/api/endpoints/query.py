import logging
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.errors import api_error
from app.services.orchestrator import run_query
from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

class QueryRequest(BaseModel):
    prompt: str
    study_id: str
    chat_id: str | None = None

def _ensure_chat_access(chat_id: str, study_id: str):
    con = get_db()
    row = con.execute("SELECT study_id FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if not row:
        raise api_error(404, "NOT_FOUND", "Chat not found.")
    if row[0] != study_id:
        raise api_error(403, "FORBIDDEN", "Chat does not belong to this study.")

@router.post("")
async def execute_user_query(
    payload: QueryRequest,
    current_user: str = Depends(get_current_user)
):
    con = get_db()
    # 1. Assert Study Access
    study_row = con.execute("SELECT user_id FROM studies WHERE id = ?", (payload.study_id,)).fetchone()
    if not study_row:
        raise api_error(404, "NOT_FOUND", "Study not found.")
    if study_row[0] != current_user:
        raise api_error(403, "FORBIDDEN", "No access to this study.")

    # 2. Chat ID management
    chat_id = payload.chat_id
    if not chat_id:
        import uuid
        chat_id = str(uuid.uuid4())
        con.execute(
            "INSERT INTO chats (id, study_id, chat_title) VALUES (?, ?, ?)",
            (chat_id, payload.study_id, payload.prompt[:50])
        )
    else:
        _ensure_chat_access(chat_id, payload.study_id)

    user_row = con.execute("SELECT username FROM users WHERE id = ?", (current_user,)).fetchone()
    current_username = user_row[0] if user_row else "Unknown"

    async def event_stream():
        async for event in run_query(
            study_id=payload.study_id,
            chat_id=chat_id,
            prompt=payload.prompt,
            user_id=current_user,
            username=current_username
        ):
            import json
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
