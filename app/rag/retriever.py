import json
import logging
import gc
from pathlib import Path

# Heavy imports (faiss) are moved inside the function to save RAM.

logger = logging.getLogger(__name__)
MAX_CONTEXT_TOKENS = 6000
TOP_K = 100

def _rebuild_chunk_metadata(study_id: str, chunks_path: Path) -> list[str]:
    from app.db.session import get_db
    from app.services.faiss_service import chunk_text, extract_text_from_file
    
    con = get_db()
    rows = con.execute(
        """
        SELECT storage_path, file_type
        FROM files
        WHERE study_id = ? AND file_type IN ('Protocol', 'Schema_JSON')
        ORDER BY created_at ASC
        """,
        (study_id,),
    ).fetchall()

    rebuilt_chunks: list[str] = []
    for storage_path, file_type in rows:
        rebuilt_chunks.extend(chunk_text(extract_text_from_file(storage_path, file_type)))

    if rebuilt_chunks:
        with chunks_path.open("w", encoding="utf-8") as file_handle:
            json.dump({"study_id": study_id, "chunks": rebuilt_chunks}, file_handle)

    return rebuilt_chunks

def retrieve_context(study_id: str, query_text: str) -> str:
    import faiss
    from app.core.compression import count_tokens
    from app.services.faiss_service import get_chunks_path, get_embeddings, get_index_path
    
    index_path = Path(get_index_path(study_id))
    chunks_path = Path(get_chunks_path(study_id))
    logger.info(
        "Resolving RAG artifacts.",
        extra={
            "event_action": "rag_artifacts",
            "model_version": "none",
            "metadata": {
                "study_id": study_id,
                "index_path": str(index_path),
                "chunks_path": str(chunks_path),
                "index_exists": index_path.exists(),
                "chunks_exists": chunks_path.exists(),
            },
        },
    )
    
    if not index_path.exists():
        logger.warning(f"RAG index not found for study {study_id} at {index_path}. It may have been wiped by a server restart.")
        return ""

    if chunks_path.exists():
        with chunks_path.open("r", encoding="utf-8") as file_handle:
            chunk_payload = json.load(file_handle)
        chunks: list[str] = chunk_payload.get("chunks", [])
    else:
        chunks = _rebuild_chunk_metadata(study_id, chunks_path)

    if not chunks:
        return ""

    try:
        logger.info(f"Reading FAISS index from {index_path}...")
        index = faiss.read_index(str(index_path))
        
        logger.info("Fetching embedding for query...")
        force_local = getattr(index, "d", 0) == 384
        normalized_embedding = get_embeddings([query_text], force_local=force_local)
        
        logger.info(f"Searching index for top {TOP_K} chunks...")
        _, indices = index.search(normalized_embedding, min(TOP_K, len(chunks)))
        logger.info("Search complete.")

        query_lower = query_text.lower()
        indices_list = list(indices[0])
        
        # Clinical relevance re-ranking
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
        
        # Cleanup
        del index
        gc.collect()
        
        return context
    except Exception as e:
        logger.error(f"RAG retrieval failed: {e}")
        return ""
