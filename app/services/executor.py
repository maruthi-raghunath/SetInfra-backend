import logging
import re
import time
from dataclasses import dataclass

import duckdb

from app.core.config import settings
from app.services.query_engine_types import RowLimitError

logger = logging.getLogger(__name__)

LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)
MAX_ROWS = 5000


@dataclass
class QueryExecutionResult:
    rows: list[dict]
    duckdb_exec_ms: int
    sql: str


def _enforce_limit(sql: str) -> str:
    match = LIMIT_PATTERN.search(sql)
    if match is None:
        return f"{sql.rstrip().rstrip(';')} LIMIT {MAX_ROWS}"

    current_limit = int(match.group(1))
    if current_limit > MAX_ROWS:
        return LIMIT_PATTERN.sub(f"LIMIT {MAX_ROWS}", sql, count=1)
    return sql


def execute_query(sql: str) -> QueryExecutionResult:
    bounded_sql = _enforce_limit(sql)
    start = time.perf_counter()
    
    if not settings.USE_DUCKDB:
        print("[TIMING] Bypassing DuckDB... using memory list.")
        column_names = ["mock_col1", "mock_col2"]
        fetched_rows = [("val1", "val2")]
        duckdb_exec_ms = int((time.perf_counter() - start) * 1000)
        print(f"[TIMING] duckdb_query_time: {duckdb_exec_ms}ms")
        result = [dict(zip(column_names, row)) for row in fetched_rows]
        return QueryExecutionResult(rows=result, duckdb_exec_ms=duckdb_exec_ms, sql=bounded_sql)

    con = duckdb.connect(settings.DB_PATH, read_only=True)
    try:
        cursor = con.execute(bounded_sql)
        column_names = [description[0] for description in cursor.description]
        fetched_rows = cursor.fetchall()
    finally:
        con.close()

    duckdb_exec_ms = int((time.perf_counter() - start) * 1000)
    print(f"[TIMING] duckdb_query_time: {duckdb_exec_ms}ms")
        
    if len(fetched_rows) > MAX_ROWS:
        raise RowLimitError("Query result exceeds rendering caps. Please narrow your cohort search parameters.")

    result = [dict(zip(column_names, row)) for row in fetched_rows]
    logger.info(
        "DuckDB query executed.",
        extra={
            "event_action": "db_execution",
            "model_version": "none",
            "metadata": {
                "duckdb_exec_ms": duckdb_exec_ms,
                "row_count": len(result),
            },
        },
    )
    return QueryExecutionResult(rows=result, duckdb_exec_ms=duckdb_exec_ms, sql=bounded_sql)
