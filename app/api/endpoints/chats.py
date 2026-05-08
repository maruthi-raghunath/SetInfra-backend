import duckdb
from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.errors import api_error
from app.db.session import get_db

router = APIRouter()


def _assert_chat_access(chat_id: str, current_user: str) -> tuple[str, str]:
    con = get_db()
    row = con.execute(
        """
        SELECT chats.id, chats.study_id, studies.user_id
        FROM chats
        JOIN studies ON chats.study_id = studies.id
        WHERE chats.id = ?
        """,
        (chat_id,),
    ).fetchone()

    if row is None:
        raise api_error(404, "CHAT_NOT_FOUND", "Chat not found.")
    if row[2] != current_user:
        raise api_error(403, "FORBIDDEN", "You do not have access to this chat.")
    return row[0], row[1]


@router.get("")
def list_chats(
    study_id: str,
    page: int = 1,
    limit: int = 20,
    current_user: str = Depends(get_current_user),
):
    safe_page = max(1, page)
    safe_limit = max(1, min(limit, 100))
    offset = (safe_page - 1) * safe_limit

    con = get_db()
    owner = con.execute("SELECT user_id FROM studies WHERE id = ?", (study_id,)).fetchone()
    if owner is None:
        raise api_error(404, "STUDY_NOT_FOUND", "Study not found.")
    if owner[0] != current_user:
        raise api_error(403, "FORBIDDEN", "You do not have access to this study.")

    total_items = con.execute(
        "SELECT COUNT(*) FROM chats WHERE study_id = ?",
        (study_id,),
    ).fetchone()[0]
    rows = con.execute(
        """
        SELECT id, chat_title, created_at
        FROM chats
        WHERE study_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (study_id, safe_limit, offset),
    ).fetchall()

    return {
        "data": [
            {
                "id": row[0],
                "chat_title": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ],
        "meta": {
            "page": safe_page,
            "limit": safe_limit,
            "total_items": total_items,
            "total_pages": (total_items + safe_limit - 1) // safe_limit if total_items else 0,
        },
    }


@router.get("/{chat_id}/messages")
def get_chat_messages(chat_id: str, current_user: str = Depends(get_current_user)):
    """Return all messages for a chat in chronological order."""
    _assert_chat_access(chat_id, current_user)
    con = get_db()
    rows = con.execute(
        """
        SELECT id, message_body, metrics_json, created_at
        FROM chat_messages
        WHERE chat_id = ?
        ORDER BY created_at ASC
        """,
        (chat_id,),
    ).fetchall()

    import json as _json
    messages = []
    for idx, row in enumerate(rows):
        # Role inferred by insertion order: even index = user, odd = assistant
        role = "user" if idx % 2 == 0 else "assistant"
        metrics = None
        if row[2] is not None:
            try:
                metrics = _json.loads(row[2]) if isinstance(row[2], str) else row[2]
            except Exception:
                metrics = None
        messages.append({
            "id": row[0],
            "role": role,
            "message_body": row[1],
            "metrics_json": metrics,
            "created_at": row[3].isoformat() if row[3] else None,
        })

    return {"messages": messages}


@router.delete("/{chat_id}")
def delete_chat(chat_id: str, current_user: str = Depends(get_current_user)):
    _, _study_id = _assert_chat_access(chat_id, current_user)
    con = get_db()
    con.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
    con.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return {"status": "deleted"}
