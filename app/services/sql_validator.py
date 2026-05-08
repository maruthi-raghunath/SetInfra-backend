import logging
import re

import duckdb

from app.core.config import settings
from app.core.study_utils import list_study_tables
from app.services.query_engine_types import SQLGuardrailError

logger = logging.getLogger(__name__)

MUTATION_PATTERN = re.compile(
    r"\b(DROP|INSERT|UPDATE|DELETE|ALTER|TRUNCATE)\b",
    re.IGNORECASE,
)
TABLE_REFERENCE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w\.]*)",
    re.IGNORECASE,
)


def _normalize_sql(sql: str) -> str:
    # 1. Strip multi-line comments /* ... */
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # 2. Strip single-line comments -- ...
    sql = re.sub(r"--.*?(?:\n|$)", " ", sql)
    # 3. Uppercase everything
    sql = sql.upper()
    # 4. Collapse all whitespace to single space
    sql = re.sub(r"\s+", " ", sql).strip()
    return sql


def _extract_table_references(sql: str) -> set[str]:
    references: set[str] = set()
    for match in TABLE_REFERENCE_PATTERN.findall(sql):
        table_name = match.split(".")[-1].strip('"').strip("'")
        references.add(table_name)
    return references


def validate_sql(sql: str, study_id: str) -> bool:
    normalized_sql = _normalize_sql(sql)

    if normalized_sql == "NONE":
        return True

    if MUTATION_PATTERN.search(normalized_sql):
        raise SQLGuardrailError(
            "Security Guardrail Tripped: Requested operation involves an invalid mutation command."
        )

    con = duckdb.connect(settings.DB_PATH)
    try:
        active_tables = set(list_study_tables(con, study_id))
    finally:
        con.close()

    referenced_tables = _extract_table_references(sql)
    unknown_tables = sorted(table for table in referenced_tables if table not in active_tables)
    if unknown_tables:
        raise SQLGuardrailError(
            f"SQL references inactive or unknown tables: {', '.join(unknown_tables)}."
        )

    logger.info(
        "SQL passed guardrails.",
        extra={
            "event_action": "sql_validation",
            "model_version": "none",
            "metadata": {
                "study_id": study_id,
                "referenced_tables": sorted(referenced_tables),
            },
        },
    )
    return True
