import duckdb
from fastapi import APIRouter
from app.core.config import settings
import os

router = APIRouter()

@router.get("")
def health_check():
    status = {"status": "ok", "duckdb": "disconnected"}
    try:
        # DB_PATH directory must exist
        db_dir = os.path.dirname(settings.DB_PATH)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
        con = duckdb.connect(settings.DB_PATH)
        con.execute("SELECT 1")
        con.close()
        status["duckdb"] = "connected"
    except Exception as e:
        status["error"] = str(e)
    return status
