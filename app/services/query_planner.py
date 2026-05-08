import json
import logging
import time
import uuid
from dataclasses import dataclass

from google import genai
from pydantic import BaseModel, Field, ValidationError

from app.core.compression import count_tokens, get_cached_schema
from app.core.config import settings
from app.services.prompt_loader import load_prompt_template
from app.services.query_engine_types import QueryPlanError

logger = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    target_tables: list[str] = Field(default_factory=list)
    sql: str
    chart_type: str


@dataclass
class QueryPlanResult:
    plan: dict
    rag_ms: int
    llm_ms: int
    prompt_tokens_estimate: int
    llm_prompt: str


def _build_client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise QueryPlanError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _parse_query_plan(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    parsed = json.loads(cleaned)
    if isinstance(parsed, list) and len(parsed) > 0:
        parsed = parsed[0]
        
    validated = QueryPlan.model_validate(parsed)
    return validated.model_dump()


def plan_query(study_id: str, prompt: str, rag_context: str) -> QueryPlanResult:
    compressed_schema = get_cached_schema(study_id)
    if compressed_schema is None:
        raise QueryPlanError(
            f"Compressed schema cache is missing for study {study_id}. "
            "Re-process the study before planning queries."
        )

    template = load_prompt_template("query_planner_v1.txt")
    assembled_prompt = template.format(
        compressed_schema=json.dumps(compressed_schema, indent=2),
        rag_context=rag_context or "No additional RAG context available.",
        user_prompt=prompt,
    )
    prompt_tokens_estimate = int(count_tokens(assembled_prompt))

    client = _build_client()
    rag_ms = 0
    llm_start = time.perf_counter()
    last_raw_response = ""
    trace_id = str(uuid.uuid4())

    for attempt in range(2):
        response = client.models.generate_content(
            model=settings.LLM_MODEL,
            contents=assembled_prompt,
            config={
                "temperature": 0,
                "response_mime_type": "application/json",
            },
        )
        last_raw_response = getattr(response, "text", "") or ""

        try:
            plan = _parse_query_plan(last_raw_response)
            llm_ms = int((time.perf_counter() - llm_start) * 1000)
            print(f"[TIMING] gemini_api_time: {llm_ms}ms (Planner)")
            logger.info(
                "Query plan generated.",
                extra={
                    "trace_id": trace_id,
                    "event_action": "query_planning",
                    "model_version": settings.LLM_MODEL,
                    "metadata": {
                        "study_id": study_id,
                        "attempt": attempt + 1,
                        "rag_ms": rag_ms,
                        "llm_ms": llm_ms,
                        "prompt_tokens_estimate": prompt_tokens_estimate,
                    },
                },
            )
            return QueryPlanResult(
                plan=plan,
                rag_ms=rag_ms,
                llm_ms=llm_ms,
                prompt_tokens_estimate=prompt_tokens_estimate,
                llm_prompt=assembled_prompt,
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt == 1:
                logger.error(
                    "Query planner failed to return valid JSON.",
                    extra={
                        "trace_id": trace_id,
                        "event_action": "query_planning",
                        "model_version": settings.LLM_MODEL,
                        "metadata": {
                            "study_id": study_id,
                            "prompt": assembled_prompt,
                            "raw_response": last_raw_response,
                            "error": str(exc),
                        },
                    },
                )
                raise QueryPlanError(
                    "AI Engine could not safely plan the query architecture.",
                    raw_response=last_raw_response,
                ) from exc

    raise QueryPlanError(
        "AI Engine could not safely plan the query architecture.",
        raw_response=last_raw_response,
    )
