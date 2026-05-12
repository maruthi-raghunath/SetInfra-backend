import duckdb
import os

from app.core.config import settings


def init_db() -> None:
    db_dir = os.path.dirname(settings.DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    con = duckdb.connect(settings.DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR PRIMARY KEY,
            username VARCHAR UNIQUE NOT NULL,
            password_hash VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    
    # Seed Maruthi1
    from app.core.security import get_password_hash
    seed_hash = get_password_hash("Password123!")
    con.execute(
        """
        INSERT INTO users (id, username, password_hash) 
        SELECT 'uuid-developer-1', 'Maruthi1', ? 
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = 'uuid-developer-1')
        """,
        (seed_hash,)
    )

    # Seed Admin
    admin_hash = get_password_hash("Admin")
    con.execute(
        """
        INSERT INTO users (id, username, password_hash) 
        SELECT 'uuid-admin-1', 'Admin', ? 
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = 'uuid-admin-1')
        """,
        (admin_hash,)
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS studies (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL,
            study_name VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute("ALTER TABLE studies ADD COLUMN IF NOT EXISTS compressed_schema JSON")
    con.execute("ALTER TABLE studies ADD COLUMN IF NOT EXISTS original_tokens INTEGER")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            id VARCHAR PRIMARY KEY,
            study_id VARCHAR NOT NULL,
            file_name VARCHAR NOT NULL,
            file_type VARCHAR NOT NULL,
            storage_path VARCHAR NOT NULL,
            is_processed BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            id VARCHAR PRIMARY KEY,
            study_id VARCHAR NOT NULL,
            chat_title VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id VARCHAR PRIMARY KEY,
            chat_id VARCHAR NOT NULL,
            message_body TEXT NOT NULL,
            metrics_json JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id VARCHAR PRIMARY KEY,
            study_id VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL,
            prompt_trace TEXT,
            sql_executed TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    studies_count = con.execute("SELECT COUNT(*) FROM studies").fetchone()[0]
    logger.info(f"Database initialized. Current study count: {studies_count}")

    # Add created_at to any existing tables that might not have it
    con.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    con.execute("ALTER TABLE studies ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    con.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    con.execute("ALTER TABLE chats ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    con.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    con.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    con.close()
