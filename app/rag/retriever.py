import json
import logging
from pathlib import Path

import duckdb
import faiss
import numpy as np

from app.core.compression import count_tokens
from app.core.config import settings
from app.services.faiss_service import (
    chunk_text,
    extract_text_from_file,
    get_chunks_path,
    get_embedding_model,
    get_index_path,
)

logger = logging.getLogger(__name__)
MAX_CONTEXT_TOKENS = 6000
TOP_K = 1000


def _rebuild_chunk_metadata(study_id: str, chunks_path: Path) -> list[str]:
    con = duckdb.connect(settings.DB_PATH)
    try:
        rows = con.execute(
            """
            SELECT storage_path, file_type
            FROM files
            WHERE study_id = ? AND file_type IN ('Protocol', 'Schema_JSON')
            ORDER BY created_at ASC
            """,
            (study_id,),
        ).fetchall()
    finally:
        con.close()

    rebuilt_chunks: list[str] = []
    for storage_path, file_type in rows:
        rebuilt_chunks.extend(chunk_text(extract_text_from_file(storage_path, file_type)))

    if rebuilt_chunks:
        with chunks_path.open("w", encoding="utf-8") as file_handle:
            json.dump({"study_id": study_id, "chunks": rebuilt_chunks}, file_handle)

    return rebuilt_chunks


def retrieve_context(study_id: str, query_text: str) -> str:
    index_path = Path(get_index_path(study_id))
    chunks_path = Path(get_chunks_path(study_id))
    if not index_path.exists():
        logger.warning(
            "RAG index not found; continuing without RAG context.",
            extra={
                "event_action": "rag_retrieval",
                "model_version": "all-MiniLM-L6-v2",
                "metadata": {
                    "study_id": study_id,
                    "index_exists": index_path.exists(),
                },
            },
        )
        return ""

    if chunks_path.exists():
        with chunks_path.open("r", encoding="utf-8") as file_handle:
            chunk_payload = json.load(file_handle)
        chunks: list[str] = chunk_payload.get("chunks", [])
    else:
        chunks = _rebuild_chunk_metadata(study_id, chunks_path)

    if not chunks:
        logger.warning(
            "RAG chunk metadata unavailable; continuing without RAG context.",
            extra={
                "event_action": "rag_retrieval",
                "model_version": "all-MiniLM-L6-v2",
                "metadata": {
                    "study_id": study_id,
                    "chunks_path": str(chunks_path),
                },
            },
        )
        return ""

    index = faiss.read_index(str(index_path))
    query_embedding = get_embedding_model().encode([query_text], convert_to_numpy=True)
    normalized_embedding = np.asarray(query_embedding, dtype=np.float32)
    _, indices = index.search(normalized_embedding, min(TOP_K, len(chunks)))

    # Re-ranking heuristic for clinical opposites (Inclusion vs Exclusion)
    query_lower = query_text.lower()
    indices_list = list(indices[0])
    
    if "inclusion" in query_lower or "exclusion" in query_lower:
        primary = "inclusion" if "inclusion" in query_lower else "exclusion"
        secondary = "exclusion" if "inclusion" in query_lower else "inclusion"
        
        def rank_score(idx):
            if idx < 0 or idx >= len(chunks): return -1
            txt = chunks[idx].lower()
            score = 0
            if "inclusion criteria" in txt or "exclusion criteria" in txt: score += 5
            if primary in txt and secondary not in txt: score += 3
            elif primary in txt: score += 2
            elif secondary in txt: score += 1
            
            # Slightly penalize Schema_JSON chunks so Protocol documents win ties
            if "[sheet:" in txt:
                score -= 2
            return score
            
        indices_list.sort(key=rank_score, reverse=True)

    selected_chunks: list[str] = []
    for chunk_index in indices_list:
        if chunk_index < 0 or chunk_index >= len(chunks):
            continue
        candidate = chunks[chunk_index]
        tentative = "\n\n".join(selected_chunks + [candidate])
        if count_tokens(tentative) > MAX_CONTEXT_TOKENS:
            break
        selected_chunks.append(candidate)

    context = "\n\n".join(selected_chunks)
    logger.info(
        "RAG context retrieved.",
        extra={
            "event_action": "rag_retrieval",
            "model_version": "all-MiniLM-L6-v2",
            "metadata": {
                "study_id": study_id,
                "requested_top_k": TOP_K,
                "returned_chunks": len(selected_chunks),
                "estimated_tokens": int(count_tokens(context)) if context else 0,
            },
        },
    )
    return context
