import logging
import os
import shutil
import uuid

import duckdb
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import get_current_user
from app.core.compression import clear_cached_schema
from app.core.config import settings
from app.core.errors import api_error
from app.core.study_utils import list_study_tables
from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class StudyCreateRequest(BaseModel):
    study_name: str = Field(min_length=1, max_length=255)


@router.post("")
def create_study(
    payload: StudyCreateRequest,
    current_user: str = Depends(get_current_user),
):
    study_id = str(uuid.uuid4())
    con = get_db()
    
    # Simple execute with auto-commit (DuckDB default)
    con.execute(
        """
        INSERT INTO studies (id, user_id, study_name, status)
        VALUES (?, ?, ?, ?)
        """,
        (study_id, current_user, payload.study_name.strip(), "Draft"),
    )
    
    logger.info(f"Study created: {study_id} for user {current_user}")
    return {"study_id": study_id, "status": "Draft"}

@router.get("")
def list_studies(page: int = 1, limit: int = 20, current_user: str = Depends(get_current_user)):
    safe_page = max(1, page)
    safe_limit = max(1, min(limit, 100))
    offset = (safe_page - 1) * safe_limit

    con = get_db()
    total_items = con.execute(
        "SELECT COUNT(*) FROM studies WHERE user_id = ?",
        (current_user,),
    ).fetchone()[0]

    rows = con.execute(
        """
        SELECT id, study_name, status, created_at
        FROM studies
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (current_user, safe_limit, offset),
    ).fetchall()

    return {
        "data": [
            {
                "id": row[0],
                "study_name": row[1],
                "status": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
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

@router.delete("/{study_id}")
def delete_study(study_id: str, current_user: str = Depends(get_current_user)):
    con = get_db()
    owner = con.execute("SELECT user_id FROM studies WHERE id = ?", (study_id,)).fetchone()

    if owner is None:
        raise api_error(404, "STUDY_NOT_FOUND", "Study not found.")
    if owner[0] != current_user:
        raise api_error(403, "FORBIDDEN", "You do not have access to this study.")

    internal_delete_study(study_id)
    return {"status": "deleted"}

def internal_delete_study(study_id: str):
    con = get_db()
    study_tables = list_study_tables(con, study_id)
    file_rows = con.execute("SELECT storage_path FROM files WHERE study_id = ?", (study_id,)).fetchall()

    for table_name in study_tables:
        con.execute(f"DROP TABLE IF EXISTS {table_name}")

    con.execute("DELETE FROM chat_messages WHERE chat_id IN (SELECT id FROM chats WHERE study_id = ?)", (study_id,))
    con.execute("DELETE FROM chats WHERE study_id = ?", (study_id,))
    con.execute("DELETE FROM files WHERE study_id = ?", (study_id,))
    con.execute("DELETE FROM audit_logs WHERE study_id = ?", (study_id,))
    con.execute("DELETE FROM studies WHERE id = ?", (study_id,))

    for (storage_path,) in file_rows:
        if storage_path and os.path.exists(storage_path):
            try:
                os.remove(storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete file {storage_path}: {e}")

    study_dir = os.path.join(settings.UPLOAD_DIR, study_id)
    if os.path.isdir(study_dir):
        try:
            shutil.rmtree(study_dir)
        except Exception as e:
            logger.warning(f"Failed to delete directory {study_dir}: {e}")

    vector_index = os.path.join(settings.VECTOR_DIR, f"{study_id}.index")
    if os.path.exists(vector_index):
        try:
            os.remove(vector_index)
        except Exception as e:
            logger.warning(f"Failed to delete FAISS index {vector_index}: {e}")

    clear_cached_schema(study_id)
    logger.info("Study deleted.", extra={"event_action": "db_execution", "model_version": "none", "metadata": {"study_id": study_id, "tables_deleted": len(study_tables)}})
