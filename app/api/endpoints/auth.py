import logging
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import create_access_token, get_current_user
from app.core.config import settings
from app.core.errors import api_error
from app.core.security import get_password_hash, verify_password
from app.db.session import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6)

class UserLogin(BaseModel):
    username: str
    password: str

@router.post("/register")
def register_user(payload: UserCreate):
    con = get_db()
    # Check if username exists
    existing = con.execute("SELECT id FROM users WHERE username = ?", (payload.username,)).fetchone()
    if existing:
        raise api_error(400, "BAD_REQUEST", "User name not available. Choose another user name.")
    
    user_id = str(uuid.uuid4())
    hashed_password = get_password_hash(payload.password)
    
    con.execute(
        """
        INSERT INTO users (id, username, password_hash)
        VALUES (?, ?, ?)
        """,
        (user_id, payload.username, hashed_password)
    )
    return {"status": "Sign Up is successful"}

@router.post("/login")
def login_user(payload: UserLogin):
    con = get_db()
    user = con.execute("SELECT id, password_hash, username FROM users WHERE username = ?", (payload.username,)).fetchone()
    if not user or not verify_password(payload.password, user[1]):
        raise api_error(401, "UNAUTHORIZED", "Invalid username or password.")
        
    access_token = create_access_token(subject=user[0])
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user[0],
        "username": user[2]
    }

@router.get("/check-username")
def check_username(username: str):
    con = get_db()
    existing = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return {"is_unique": existing is None}

@router.get("/users")
def get_users(current_user: str = Depends(get_current_user)):
    con = get_db()
    current_username = con.execute("SELECT username FROM users WHERE id = ?", (current_user,)).fetchone()
    if not current_username or current_username[0] != "Admin":
        raise api_error(403, "FORBIDDEN", "Only Admin can view users.")
        
    rows = con.execute("SELECT id, username, created_at FROM users ORDER BY created_at DESC").fetchall()
    return {
        "data": [
            {
                "id": row[0],
                "username": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ]
    }

@router.delete("/users/{user_id}")
def delete_user(user_id: str, current_user: str = Depends(get_current_user)):
    con = get_db()
    # Check if requester is Admin
    current_username = con.execute("SELECT username FROM users WHERE id = ?", (current_user,)).fetchone()
    if not current_username or current_username[0] != "Admin":
        raise api_error(403, "FORBIDDEN", "Only Admin can delete users.")
    
    # Check if target user exists
    target = con.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        raise api_error(404, "NOT_FOUND", "User not found.")
    
    # Do not allow deleting Admin
    if target[0] == "Admin":
        raise api_error(400, "BAD_REQUEST", "Cannot delete Admin user.")

    # Cascading delete logic
    # 1. Get all studies for this user
    studies = con.execute("SELECT id FROM studies WHERE user_id = ?", (user_id,)).fetchall()
    
    from app.api.endpoints.studies import internal_delete_study
    for (study_id,) in studies:
        internal_delete_study(study_id)
        
    # 2. Delete user
    con.execute("DELETE FROM users WHERE id = ?", (user_id,))
    
    logger.info(f"User {target[0]} deleted by Admin.")
    return {"status": "deleted"}
