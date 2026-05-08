import logging
import os
import uuid
from pathlib import Path

import duckdb
from fastapi import APIRouter, Depends, File, Form, UploadFile, BackgroundTasks

from app.core.auth import get_current_user
from app.core.compression import clear_cached_schema, compress_schema
from app.core.config import settings
from app.core.errors import api_error
from app.core.study_utils import build_sdtm_table_name, list_study_tables
from app.services.faiss_service import index_documents

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "Protocol": {".pdf", ".docx"},
    "Schema_JSON": {".csv", ".xls", ".xlsx"},
    "SDTM_CSV": {".csv"},
}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _assert_study_access(
    con: duckdb.DuckDBPyConnection,
    study_id: str,
    current_user: str,
) -> None:
    owner = con.execute("SELECT user_id FROM studies WHERE id = ?", (study_id,)).fetchone()
    if owner is None:
        raise api_error(404, "STUDY_NOT_FOUND", "Study not found.")
    if owner[0] != current_user:
        raise api_error(403, "FORBIDDEN", "You do not have access to this study.")


async def _save_upload(study_id: str, file_id: str, upload: UploadFile) -> str:
    study_dir = Path(settings.UPLOAD_DIR) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = Path(upload.filename or "upload.bin").name
    destination = study_dir / f"{file_id}_{safe_filename}"

    total_bytes = 0
    with destination.open("wb") as file_handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_BYTES:
                file_handle.close()
                destination.unlink(missing_ok=True)
                raise api_error(400, "FILE_TOO_LARGE", "File upload exceeds the 500MB limit.")
            file_handle.write(chunk)

    await upload.close()
    return str(destination)

@router.post("/upload")
async def upload_file(
    study_id: str = Form(...),
    file_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    if file_type not in ALLOWED_TYPES:
        raise api_error(400, "INVALID_FILE_TYPE", "Unsupported file type.")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_TYPES[file_type]:
        raise api_error(
            400,
            "INVALID_FILE_EXTENSION",
            f"Unsupported extension for {file_type}.",
        )

    con = duckdb.connect(settings.DB_PATH)
    try:
        _assert_study_access(con, study_id, current_user)

        file_id = str(uuid.uuid4())
        storage_path = await _save_upload(study_id, file_id, file)
        con.execute(
            """
            INSERT INTO files (id, study_id, file_name, file_type, storage_path, is_processed)
            VALUES (?, ?, ?, ?, ?, false)
            """,
            (file_id, study_id, Path(file.filename or "").name, file_type, storage_path),
        )
    finally:
        con.close()

    return {"file_id": file_id, "status": "Uploaded"}


@router.get("")
def list_files(
    study_id: str,
    page: int = 1,
    limit: int = 20,
    current_user: str = Depends(get_current_user),
):
    safe_page = max(1, page)
    safe_limit = max(1, min(limit, 100))
    offset = (safe_page - 1) * safe_limit

    con = duckdb.connect(settings.DB_PATH)
    try:
        _assert_study_access(con, study_id, current_user)

        total_items = con.execute(
            "SELECT COUNT(*) FROM files WHERE study_id = ?",
            (study_id,),
        ).fetchone()[0]
        rows = con.execute(
            """
            SELECT id, study_id, file_name, file_type, is_processed, created_at
            FROM files
            WHERE study_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (study_id, safe_limit, offset),
        ).fetchall()
    finally:
        con.close()

    return {
        "data": [
            {
                "id": row[0],
                "study_id": row[1],
                "file_name": row[2],
                "file_type": row[3],
                "is_processed": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
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

def _internal_process_files(study_id: str):
    """Heavy lifting for file processing, meant to be run in a background task."""
    con = duckdb.connect(settings.DB_PATH)
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
            # Always collect documents for the full index
            if file_type in ["Protocol", "Schema_JSON"]:
                documents_to_embed.append((storage_path, file_type))

            # Only process new SDTM files into DuckDB tables
            if not is_processed and file_type == "SDTM_CSV":
                domain = Path(file_name).stem.lower()
                table_name = build_sdtm_table_name(study_id, domain)
                safe_path = storage_path.replace("\\", "/").replace("'", "''")
                con.execute(f"DROP TABLE IF EXISTS {table_name}")
                con.execute(
                    f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{safe_path}')"
                )
            
            if not is_processed:
                processed_file_ids.append(file_id)

        # Rebuild the full vector index for this study (Heavy Task)
        if documents_to_embed:
            index_documents(study_id, documents_to_embed)

        # Rebuild the compressed schema cache (Heavy Task)
        compress_schema(study_id, settings.DB_PATH)

        # Mark files as processed
        for f_id in processed_file_ids:
            con.execute("UPDATE files SET is_processed = true WHERE id = ?", (f_id,))
        con.execute("UPDATE studies SET status = 'Active' WHERE id = ?", (study_id,))

    except Exception as exc:
        logger.error(f"Background processing failed for study {study_id}: {exc}")
    finally:
        con.close()


@router.post("/process/{study_id}")
async def process_study_files(
    study_id: str, 
    background_tasks: BackgroundTasks,
    current_user: str = Depends(get_current_user)
):
    con = duckdb.connect(settings.DB_PATH)
    try:
        _assert_study_access(con, study_id, current_user)
    finally:
        con.close()

    background_tasks.add_task(_internal_process_files, study_id)
    return {"message": "Processing started in background."}


@router.delete("/{file_id}")
def delete_file(file_id: str, current_user: str = Depends(get_current_user)):
    con = duckdb.connect(settings.DB_PATH)
    try:
        file_record = con.execute(
            """
            SELECT study_id, storage_path, file_type, file_name
            FROM files
            WHERE id = ?
            """,
            (file_id,),
        ).fetchone()
        if not file_record:
            raise api_error(404, "FILE_NOT_FOUND", "File not found.")

        study_id = file_record[0]
        storage_path = file_record[1]
        file_type = file_record[2]
        file_name = file_record[3]

        _assert_study_access(con, study_id, current_user)

        con.execute("DELETE FROM files WHERE id = ?", (file_id,))

        if file_type == "SDTM_CSV":
            domain = Path(file_name).stem.lower()
            table_name = build_sdtm_table_name(study_id, domain)
            con.execute(f"DROP TABLE IF EXISTS {table_name}")
    finally:
        con.close()

    if storage_path and os.path.exists(storage_path):
        os.remove(storage_path)

    con = duckdb.connect(settings.DB_PATH)
    remaining_tables = list_study_tables(con, study_id)
    con.close()

    if remaining_tables:
        compress_schema(study_id, settings.DB_PATH, remaining_tables)
    else:
        clear_cached_schema(study_id)

    logger.info(
        "File deleted.",
        extra={
            "event_action": "db_execution",
            "model_version": "none",
            "metadata": {"study_id": study_id, "file_id": file_id, "file_type": file_type},
        },
    )
    return {"status": "deleted"}
