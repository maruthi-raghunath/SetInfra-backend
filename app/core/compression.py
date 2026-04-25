import json
import logging

import duckdb

from app.core.study_utils import list_study_tables

logger = logging.getLogger(__name__)

SCHEMA_CACHE: dict[str, dict] = {}
TARGET_TOKEN_BUDGET = 2000


def count_tokens(text: str) -> float:
    return len(text.split()) * 1.3


def _is_noise_column(column_name: str) -> bool:
    upper_name = column_name.upper()
    return (
        upper_name.endswith("_SEQ")
        or upper_name.endswith("_NUM")
        or upper_name == "STUDYID"
    )


def _is_priority_column(column_name: str) -> bool:
    upper_name = column_name.upper()
    return (
        "SUBJID" in upper_name
        or "USUBJID" in upper_name
        or "DT" in upper_name
        or upper_name.endswith("GR")
        or upper_name.endswith("SER")
        or upper_name.endswith("STRESN")
        or upper_name.endswith("STRESC")
    )


def compress_schema(
    study_id: str,
    db_path: str,
    created_tables: list[str] | None = None,
) -> dict:
    con = duckdb.connect(db_path, read_only=True)
    table_names = created_tables or list_study_tables(con, study_id)

    study_schema = {"study_id": study_id, "tables": {}}
    remaining_budget = TARGET_TOKEN_BUDGET

    for table_name in table_names:
        columns_data = con.execute(f"DESCRIBE {table_name}").fetchall()
        priority_columns: list[dict[str, str]] = []
        standard_columns: list[dict[str, str]] = []

        for column_name, column_type, *_ in columns_data:
            if _is_noise_column(column_name):
                continue

            column_payload = {"name": column_name, "type": column_type}
            if _is_priority_column(column_name):
                priority_columns.append(column_payload)
            else:
                standard_columns.append(column_payload)

        selected_columns = list(priority_columns)
        for column in standard_columns:
            tentative_columns = selected_columns + [column]
            tentative_schema = {
                "study_id": study_id,
                "tables": {
                    **study_schema["tables"],
                    table_name: {"columns": tentative_columns},
                },
            }
            if count_tokens(json.dumps(tentative_schema)) > TARGET_TOKEN_BUDGET:
                break
            selected_columns.append(column)

        study_schema["tables"][table_name] = {"columns": selected_columns}
        remaining_budget = TARGET_TOKEN_BUDGET - int(
            count_tokens(json.dumps(study_schema))
        )

    con.close()

    SCHEMA_CACHE[study_id] = study_schema
    logger.info(
        "Compressed schema cached.",
        extra={
            "event_action": "schema_compression",
            "model_version": "none",
            "metadata": {
                "study_id": study_id,
                "tables": len(study_schema["tables"]),
                "estimated_tokens": int(count_tokens(json.dumps(study_schema))),
                "remaining_budget": remaining_budget,
            },
        },
    )
    return study_schema


def get_cached_schema(study_id: str) -> dict | None:
    return SCHEMA_CACHE.get(study_id)


def clear_cached_schema(study_id: str) -> None:
    SCHEMA_CACHE.pop(study_id, None)


def warm_schema_cache(db_path: str) -> None:
    """Called once at startup to rebuild the in-memory schema cache from the
    persisted DuckDB tables.  Reads all study UUIDs directly from the studies
    table and uses list_study_tables to detect which ones have SDTM data,
    then rebuilds the compressed schema for each."""
    # Read all known study IDs from the studies table.
    try:
        con = duckdb.connect(db_path, read_only=True)
        all_study_ids = [row[0] for row in con.execute("SELECT id FROM studies").fetchall()]
        con.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "warm_schema_cache: could not read studies table — skipping cache warm.",
            extra={
                "event_action": "schema_compression",
                "model_version": "none",
                "metadata": {"error": str(exc)},
            },
        )
        return

    if not all_study_ids:
        return

    warmed = 0
    for study_id in all_study_ids:
        try:
            con = duckdb.connect(db_path, read_only=True)
            tables = list_study_tables(con, study_id)
            con.close()
            if tables:
                compress_schema(study_id, db_path, tables)
                warmed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "warm_schema_cache: failed to compress schema for study %s.",
                study_id,
                extra={
                    "event_action": "schema_compression",
                    "model_version": "none",
                    "metadata": {"study_id": study_id, "error": str(exc)},
                },
            )

    logger.info(
        "Schema cache warmed on startup.",
        extra={
            "event_action": "schema_compression",
            "model_version": "none",
            "metadata": {"studies_warmed": warmed},
        },
    )
