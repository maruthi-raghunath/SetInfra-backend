import duckdb
from fastapi import APIRouter
from app.core.config import settings
import os
from pydantic import BaseModel
from pathlib import Path

router = APIRouter()

class ConfigUpdate(BaseModel):
    use_local_embedding: bool

@router.get("")
def health_check():
    status = {
        "status": "ok", 
        "duckdb": "disconnected", 
        "use_local_embedding": settings.USE_LOCAL_EMBEDDING
    }
    try:
        con = duckdb.connect(settings.DB_PATH)
        con.execute("SELECT 1")
        con.close()
        status["duckdb"] = "connected"
    except Exception as e:
        status["error"] = str(e)
    return status

@router.post("/config")
def update_config(payload: ConfigUpdate):
    settings.USE_LOCAL_EMBEDDING = payload.use_local_embedding
    return {"use_local_embedding": settings.USE_LOCAL_EMBEDDING}

@router.get("/debug_studies")
def debug_studies():
    from app.db.session import get_db
    con = get_db()
    rows = con.execute("SELECT id, user_id, study_name, status FROM studies").fetchall()
    users = con.execute("SELECT id, username FROM users").fetchall()
    return {"studies": rows, "users": users}

@router.get("/reset_files")
def reset_files():
    from app.db.session import get_db
    con = get_db()
    con.execute("UPDATE files SET is_processed = false WHERE study_id = 'c7acd3f4-9bab-4a1a-a1dc-03b401af205d'")
    con.execute("UPDATE studies SET status = 'Draft' WHERE id = 'c7acd3f4-9bab-4a1a-a1dc-03b401af205d'")
    return {"status": "ok"}


@router.get("/rag/{study_id}")
def rag_status(study_id: str):
    from app.services.faiss_service import get_chunks_path, get_index_path
    from app.db.session import get_db

    con = get_db()
    study = con.execute(
        "SELECT id, status FROM studies WHERE id = ?",
        (study_id,),
    ).fetchone()
    if not study:
        return {"study_id": study_id, "exists": False, "message": "Study not found."}

    file_rows = con.execute(
        """
        SELECT id, file_name, file_type, storage_path, is_processed, created_at
        FROM files
        WHERE study_id = ?
        ORDER BY created_at ASC
        """,
        (study_id,),
    ).fetchall()

    index_path = Path(get_index_path(study_id))
    chunks_path = Path(get_chunks_path(study_id))

    def _file_info(path: Path) -> dict:
        exists = path.exists()
        return {
            "path": str(path),
            "exists": exists,
            "size_bytes": path.stat().st_size if exists else 0,
            "modified_at": path.stat().st_mtime if exists else None,
        }

    protocol_schema_files = [
        {
            "id": row[0],
            "file_name": row[1],
            "file_type": row[2],
            "storage_path": row[3],
            "storage_exists": bool(row[3]) and Path(row[3]).exists(),
            "is_processed": bool(row[4]),
            "created_at": row[5].isoformat() if row[5] else None,
        }
        for row in file_rows
        if row[2] in ("Protocol", "Schema_JSON")
    ]

    return {
        "study_id": study_id,
        "exists": True,
        "study_status": study[1],
        "config": {
            "db_path": settings.DB_PATH,
            "upload_dir": settings.UPLOAD_DIR,
            "vector_dir": settings.VECTOR_DIR,
            "use_local_embedding": settings.USE_LOCAL_EMBEDDING,
        },
        "rag_artifacts": {
            "index": _file_info(index_path),
            "chunks": _file_info(chunks_path),
        },
        "source_files": {
            "total_files": len(file_rows),
            "protocol_or_schema_files": len(protocol_schema_files),
            "items": protocol_schema_files,
        },
    }
