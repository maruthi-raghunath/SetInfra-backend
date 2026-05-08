import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, BackgroundTasks

from app.core.auth import get_current_user
from app.core.compression import clear_cached_schema, compress_schema
from app.core.config import settings
from app.core.errors import api_error
from app.core.study_utils import build_sdtm_table_name, list_study_tables
from app.services.faiss_service import index_documents
from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "Protocol": {".pdf", ".docx"},
    "SDTM_CSV": {".csv"},
    "Schema_JSON": {".json", ".csv", ".xlsx", ".xls"}
}

def _assert_study_access(con, study_id: str, user_id: str):
    row = con.execute("SELECT user_id FROM studies WHERE id = ?", (study_id,)).fetchone()
    if not row:
        raise api_error(404, "NOT_FOUND", "Study not found.")
    if row[0] != user_id:
        raise api_error(403, "FORBIDDEN", "No access to this study.")

@router.post("/upload")
async def upload_file(
    study_id: str = Form(...),
    file_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    con = get_db()
    _assert_study_access(con, study_id, current_user)

    ext = Path(file.filename).suffix.lower()
    if file_type not in ALLOWED_TYPES or ext not in ALLOWED_TYPES[file_type]:
        raise api_error(400, "INVALID_FILE_TYPE", f"Invalid file type for {file_type}")

    study_dir = os.path.join(settings.UPLOAD_DIR, study_id)
    os.makedirs(study_dir, exist_ok=True)
    
    file_id = str(uuid.uuid4())
    filename = f"{file_id}{ext}"
    storage_path = os.path.join(study_dir, filename)

    with open(storage_path, "wb") as f:
        f.write(await file.read())

    con.execute(
        """
        INSERT INTO files (id, study_id, file_name, file_type, storage_path, is_processed)
        VALUES (?, ?, ?, ?, ?, false)
        """,
        (file_id, study_id, file.filename, file_type, storage_path)
    )
    
    return {"file_id": file_id}

@router.get("/{study_id}")
def list_files(study_id: str, current_user: str = Depends(get_current_user)):
    con = get_db()
    _assert_study_access(con, study_id, current_user)
    
    rows = con.execute(
        "SELECT id, file_name, file_type, is_processed, created_at FROM files WHERE study_id = ? ORDER BY created_at DESC",
        (study_id,)
    ).fetchall()
    
    return {
        "data": [
            {
                "id": row[0],
                "file_name": row[1],
                "file_type": row[2],
                "is_processed": row[3],
                "created_at": row[4].isoformat() if row[4] else None
            }
            for row in rows
        ]
    }

def _internal_process_files(study_id: str):
    """Heavy lifting for file processing, run in a background task."""
    con = get_db()
    try:
        # Get ALL files for this study to ensure complete indexing/schema
        all_files = con.execute(
            """
            SELECT id, file_type, storage_path, file_name, is_processed
            FROM files
            WHERE study_id = ?
            ORDER BY created_at ASC
            """,
            (study_id,)
        ).fetchall()

        if not all_files:
            return

        con.execute("UPDATE studies SET status = 'Processing' WHERE id = ?", (study_id,))

        documents_to_embed = []
        processed_file_ids: list[str] = []

        for file_id, file_type, storage_path, file_name, is_processed in all_files:
            if file_type in ["Protocol", "Schema_JSON"]:
                documents_to_embed.append((storage_path, file_type))

            if not is_processed and file_type == "SDTM_CSV":
                domain = Path(file_name).stem.lower()
                table_name = build_sdtm_table_name(study_id, domain)
                safe_path = storage_path.replace("\\", "/").replace("'", "''")
                con.execute(f"DROP TABLE IF EXISTS {table_name}")
                con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{safe_path}')")
            
            if not is_processed:
                processed_file_ids.append(file_id)

        if documents_to_embed:
            index_documents(study_id, documents_to_embed)

        compress_schema(study_id, settings.DB_PATH)

        for f_id in processed_file_ids:
            con.execute("UPDATE files SET is_processed = true WHERE id = ?", (f_id,))
        con.execute("UPDATE studies SET status = 'Active' WHERE id = ?", (study_id,))

    except Exception as exc:
        logger.error(f"Background processing failed for study {study_id}: {exc}")
        try:
            con.execute("UPDATE studies SET status = 'Error' WHERE id = ?", (study_id,))
        except:
            pass

@router.post("/process/{study_id}")
async def process_study_files(
    study_id: str, 
    background_tasks: BackgroundTasks,
    current_user: str = Depends(get_current_user)
):
    con = get_db()
    _assert_study_access(con, study_id, current_user)

    background_tasks.add_task(_internal_process_files, study_id)
    return {"message": "Processing started in background."}

@router.delete("/{file_id}")
def delete_file(file_id: str, current_user: str = Depends(get_current_user)):
    con = get_db()
    file_info = con.execute("SELECT study_id, storage_path, is_processed FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file_info:
        raise api_error(404, "NOT_FOUND", "File not found.")
    
    study_id, storage_path, is_processed = file_info
    _assert_study_access(con, study_id, current_user)
    
    con.execute("DELETE FROM files WHERE id = ?", (file_id,))
    if storage_path and os.path.exists(storage_path):
        os.remove(storage_path)
    
    clear_cached_schema(study_id)
    return {"status": "deleted"}
