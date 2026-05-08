import asyncio
import json
import time

from google import genai

from app.core.config import settings
from app.services.prompt_loader import load_prompt_template
from app.services.query_engine_types import ExplanationError


def _build_client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise ExplanationError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _summarize_rows(rows: list[dict], limit: int = 20) -> str:
    return json.dumps({"row_count": len(rows), "sample_rows": rows[:limit]}, indent=2, default=str)


async def explain_results(dataframe: list[dict], stats: dict, prompt: str, rag_context: str):
    template = load_prompt_template("explanation_v1.txt")
    assembled_prompt = template.format(
        sql_results_summary=_summarize_rows(dataframe),
        stats_output=json.dumps(stats, indent=2, default=str),
        rag_context=rag_context or "No additional RAG context available.",
        user_prompt=prompt,
    )

    client = _build_client()
    llm_start = time.perf_counter()
    first_token_time = None
    stream = client.models.generate_content_stream(
        model=settings.LLM_MODEL,
        contents=assembled_prompt,
        config={
            "temperature": 0,
            "thinking_config": {"thinking_level": "minimal"},
        },
    )
    for chunk in stream:
        if first_token_time is None:
            first_token_time = int((time.perf_counter() - llm_start) * 1000)
            print(f"[TIMING] gemini_api_time: {first_token_time}ms (Explanation First Token)")
        text = getattr(chunk, "text", "") or ""
        if not text:
            continue
        yield text
        await asyncio.sleep(0)
