import re
from typing import Any


def normalize_identifier_segment(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip().lower())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "value"


def build_sdtm_table_name(study_id: str, domain: str) -> str:
    return f"sdtm_{normalize_identifier_segment(study_id)}_{normalize_identifier_segment(domain)}"


def list_study_tables(connection: Any, study_id: str) -> list[str]:
    prefix = f"sdtm_{normalize_identifier_segment(study_id)}_%"
    rows = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name LIKE ?
        ORDER BY table_name
        """,
        (prefix,),
    ).fetchall()
    return [row[0] for row in rows]
