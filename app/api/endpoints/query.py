import json
import uuid

import duckdb
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.errors import api_error
from app.services.orchestrator import run_query

router = APIRouter()


class QueryRequest(BaseModel):
    study_id: str
    chat_id: str | None = None
    prompt: str


def _ensure_study_access(study_id: str, current_user: str) -> None:
    con = duckdb.connect(settings.DB_PATH)
    try:
        owner = con.execute("SELECT user_id FROM studies WHERE id = ?", (study_id,)).fetchone()
    finally:
        con.close()

    if owner is None:
        raise api_error(404, "STUDY_NOT_FOUND", "Study not found.")
    if owner[0] != current_user:
        raise api_error(403, "FORBIDDEN", "You do not have access to this study.")


def _ensure_chat_access(chat_id: str, study_id: str) -> None:
    con = duckdb.connect(settings.DB_PATH)
    try:
        chat_row = con.execute(
            "SELECT id FROM chats WHERE id = ? AND study_id = ?",
            (chat_id, study_id),
        ).fetchone()
    finally:
        con.close()

    if chat_row is None:
        raise api_error(404, "CHAT_NOT_FOUND", "Chat not found.")


def _create_chat(study_id: str, prompt: str) -> str:
    chat_id = str(uuid.uuid4())
    title = prompt.strip()[:80] or "New Chat"
    con = duckdb.connect(settings.DB_PATH)
    try:
        con.execute(
            "INSERT INTO chats (id, study_id, chat_title) VALUES (?, ?, ?)",
            (chat_id, study_id, title),
        )
    finally:
        con.close()
    return chat_id


@router.post("")
async def query_endpoint(
    payload: QueryRequest,
    current_user: str = Depends(get_current_user),
):
    _ensure_study_access(payload.study_id, current_user)
    chat_id = payload.chat_id
    if chat_id is None:
        chat_id = _create_chat(payload.study_id, payload.prompt)
    else:
        _ensure_chat_access(chat_id, payload.study_id)

    con_user = duckdb.connect(settings.DB_PATH, read_only=True)
    try:
        user_row = con_user.execute("SELECT username FROM users WHERE id = ?", (current_user,)).fetchone()
        current_username = user_row[0] if user_row else "Unknown"
    finally:
        con_user.close()

    async def event_stream():
        async for event in run_query(payload.study_id, chat_id, payload.prompt, current_user, current_username):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
