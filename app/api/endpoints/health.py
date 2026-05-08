import duckdb
from fastapi import APIRouter
from app.core.config import settings
import os
from pydantic import BaseModel

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
