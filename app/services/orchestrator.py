import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator

import duckdb

from app.core.config import gemini_api_key_preview, settings
from app.rag.retriever import retrieve_context
from app.services.executor import execute_query
from app.services.explainer import explain_results
from app.services.query_engine_types import AuditLogError, QueryEngineError
from app.services.query_planner import plan_query
from app.services.sql_validator import validate_sql
from app.services.stats_validator import validate_results

logger = logging.getLogger(__name__)


def _event(name: str, payload: dict) -> dict:
    return {"event": name, "payload": payload}


async def _save_chat_and_audit_async(
    *,
    chat_id: str,
    study_id: str,
    prompt: str,
    assistant_message: str,
    metrics: dict,
    sql: str,
) -> None:
    def _do_save():
        con = duckdb.connect(settings.DB_PATH)
        try:
            con.execute("BEGIN TRANSACTION")
            con.execute(
                """
                INSERT INTO chat_messages (id, chat_id, message_body, metrics_json)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), chat_id, prompt, None),
            )
            con.execute(
                """
                INSERT INTO chat_messages (id, chat_id, message_body, metrics_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    chat_id,
                    assistant_message,
                    json.dumps(metrics, default=str),
                ),
            )
            con.execute(
                """
                INSERT INTO audit_logs (id, study_id, event_type, prompt_trace, sql_executed)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    study_id,
                    "Query_Execution",
                    prompt,
                    sql,
                ),
            )
            con.execute("COMMIT")
        except Exception as exc:
            con.execute("ROLLBACK")
            raise AuditLogError("Failed to persist chat and audit log transaction.") from exc
        finally:
            con.close()
            
    await asyncio.to_thread(_do_save)


async def run_query(study_id: str, chat_id: str, prompt: str, user_id: str, username: str) -> AsyncGenerator[dict, None]:
    trace_id = str(uuid.uuid4())
    total_start = time.perf_counter()
    rag_context = ""
    assistant_chunks: list[str] = []
    metrics: dict = {
        "trace_id": trace_id,
        "gemini_api_key_preview": gemini_api_key_preview(),
        "llm_model": settings.LLM_MODEL,
    }
    executed_sql = ""

    try:
        yield _event("thinking", {"stage": "rag", "chat_id": chat_id})
        rag_start = time.perf_counter()
        rag_context = await asyncio.to_thread(retrieve_context, study_id, prompt)
        rag_ms = int((time.perf_counter() - rag_start) * 1000)
        metrics["rag_ms"] = rag_ms

        yield _event("thinking", {"stage": "planning", "chat_id": chat_id})
        plan_result = await asyncio.to_thread(plan_query, study_id, prompt, rag_context)
        metrics["planner_llm_ms"] = plan_result.llm_ms
        metrics["prompt_tokens_estimate"] = plan_result.prompt_tokens_estimate
        metrics["rag_context_present"] = bool(rag_context)

        executed_sql = plan_result.plan["sql"]
        await asyncio.to_thread(validate_sql, executed_sql, study_id)
        yield _event("sql_ready", {"sql": executed_sql, "chat_id": chat_id})

        execution_result = await asyncio.to_thread(execute_query, executed_sql)
        metrics["duckdb_exec_ms"] = execution_result.duckdb_exec_ms
        yield _event(
            "data_ready",
            {
                "rows": execution_result.rows,
                "chart_type": plan_result.plan["chart_type"],
                "chat_id": chat_id,
            },
        )

        stats_result = await asyncio.to_thread(validate_results, execution_result.rows)
        metrics["stats_skipped"] = stats_result["skipped"]
        metrics["row_count"] = stats_result["row_count"]

        # If data is insufficient but it's a Protocol question (SQL is empty or "NONE"), 
        # we MUST still explain using RAG context.
        force_explanation = (not executed_sql) or (executed_sql.strip().upper() == "NONE")

        if stats_result["skipped"] and not force_explanation:
            assistant_text = stats_result["reason"]
            assistant_chunks.append(assistant_text)
            yield _event("explanation", {"chunk": assistant_text, "chat_id": chat_id})
        else:
            first_byte_ms = None
            explanation_start = time.perf_counter()
            async for chunk in explain_results(execution_result.rows, stats_result, prompt, rag_context):
                if first_byte_ms is None:
                    first_byte_ms = int((time.perf_counter() - explanation_start) * 1000)
                    metrics["first_byte_ms"] = first_byte_ms
                assistant_chunks.append(chunk)
                yield _event("explanation", {"chunk": chunk, "chat_id": chat_id})

        assistant_message = "".join(assistant_chunks).strip()
        if not assistant_message:
            assistant_message = "No explanation generated."

        from app.core.compression import get_original_tokens
        original_tokens = await asyncio.to_thread(get_original_tokens, study_id, settings.DB_PATH)
        actual_tokens = plan_result.prompt_tokens_estimate
        savings_percentage = 0.0
        if original_tokens > 0:
            savings_percentage = round(((original_tokens - actual_tokens) / original_tokens) * 100, 2)
            
        metrics["compression_stats"] = {
            "original_tokens": original_tokens,
            "actual_tokens": actual_tokens,
            "savings_percentage": savings_percentage
        }

        metrics["total_latency_ms"] = int((time.perf_counter() - total_start) * 1000)
        print(f"[TIMING] total_processing_time: {metrics['total_latency_ms']}ms")
        metrics["chart_type"] = plan_result.plan["chart_type"]
        metrics["data_rows"] = execution_result.rows
        metrics["sql_query"] = executed_sql
        metrics["audit_log"] = {
            "prompt_id": trace_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "llm_prompt": plan_result.llm_prompt,
            "sql_query": executed_sql,
            "rag_context": rag_context,
            "user_id": user_id,
            "username": username,
            "model_name": settings.LLM_MODEL,
            "prompt_name": prompt,
        }

        await _save_chat_and_audit_async(
            chat_id=chat_id,
            study_id=study_id,
            prompt=prompt,
            assistant_message=assistant_message,
            metrics=metrics,
            sql=execution_result.sql,
        )

        yield _event("metrics", metrics)
    except (QueryEngineError, Exception) as exc:
        logger.error(
            "Query orchestration failed.",
            extra={
                "trace_id": trace_id,
                "event_action": "query_orchestration",
                "model_version": settings.LLM_MODEL,
                "metadata": {
                    "study_id": study_id,
                    "chat_id": chat_id,
                    "error": str(exc),
                },
            },
        )
        yield _event("error", {"message": str(exc), "chat_id": chat_id})
    finally:
        yield _event("done", {"chat_id": chat_id})
