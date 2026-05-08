import uuid
import duckdb
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.auth import create_access_token
from app.core.security import get_password_hash, verify_password
from app.core.errors import api_error

router = APIRouter()

class UserRegister(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=8)

class UserLogin(BaseModel):
    username: str
    password: str

@router.post("/register")
def register_user(payload: UserRegister):
    con = duckdb.connect(settings.DB_PATH)
    try:
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
    finally:
        con.close()

@router.post("/login")
def login_user(payload: UserLogin):
    con = duckdb.connect(settings.DB_PATH)
    try:
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
    finally:
        con.close()

@router.get("/check-username")
def check_username(username: str):
    con = duckdb.connect(settings.DB_PATH)
    try:
        existing = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        return {"is_unique": existing is None}
    finally:
        con.close()

from app.core.auth import get_current_user
from fastapi import Depends

@router.get("/users")
def get_users(current_user: str = Depends(get_current_user)):
    con = duckdb.connect(settings.DB_PATH)
    try:
        current_username = con.execute("SELECT username FROM users WHERE id = ?", (current_user,)).fetchone()
        if not current_username or current_username[0] != "Admin":
            raise api_error(403, "FORBIDDEN", "Only Admin can view users.")
            
        users = con.execute("SELECT id, username FROM users WHERE username != 'Admin' AND username != 'Maruthi1'").fetchall()
        # Including Maruthi1 or not? The prompt doesn't say "except Maruthi1". Better to show all except Admin.
        users = con.execute("SELECT id, username FROM users WHERE username != 'Admin'").fetchall()
        return {"data": [{"id": row[0], "username": row[1]} for row in users]}
    finally:
        con.close()

@router.delete("/users/{user_id}")
def delete_user(user_id: str, current_user: str = Depends(get_current_user)):
    con = duckdb.connect(settings.DB_PATH)
    try:
        current_username = con.execute("SELECT username FROM users WHERE id = ?", (current_user,)).fetchone()
        if not current_username or current_username[0] != "Admin":
            raise api_error(403, "FORBIDDEN", "Only Admin can delete users.")
            
        # Refuse to delete the Admin
        target_username = con.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if target_username and target_username[0] == "Admin":
            raise api_error(400, "BAD_REQUEST", "Cannot delete Admin user.")

        # Get all studies for this user
        studies = con.execute("SELECT id FROM studies WHERE user_id = ?", (user_id,)).fetchall()
        from app.api.endpoints.studies import internal_delete_study
        
        for (sid,) in studies:
            internal_delete_study(sid)

        # Delete user
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return {"status": "User deleted"}
    finally:
        con.close()
