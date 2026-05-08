from __future__ import annotations
import csv

import json
import logging
import os
from typing import Any

import faiss
import numpy as np
import PyPDF2
from docx import Document
from openpyxl import load_workbook
import xlrd

from app.core.config import settings

logger = logging.getLogger(__name__)

_model: Any = None
CHUNKS_SUFFIX = ".chunks.json"


def _get_model() -> Any:
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")

def get_embedding_model() -> Any:
    return _get_model()


def get_index_path(study_id: str) -> str:
    return os.path.join(settings.VECTOR_DIR, f"{study_id}.index")


def get_chunks_path(study_id: str) -> str:
    return os.path.join(settings.VECTOR_DIR, f"{study_id}{CHUNKS_SUFFIX}")


def extract_text_from_file(file_path: str, file_type: str) -> str:
    if file_type == "Protocol":
        if file_path.lower().endswith(".pdf"):
            text_parts: list[str] = []
            with open(file_path, "rb") as file_handle:
                reader = PyPDF2.PdfReader(file_handle)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text_parts.append(extracted)
            return "\n".join(text_parts)

        if file_path.lower().endswith(".docx"):
            document = Document(file_path)
            return "\n".join(
                paragraph.text for paragraph in document.paragraphs if paragraph.text
            )

    if file_type == "Schema_JSON":
        if file_path.lower().endswith(".csv"):
            with open(file_path, "r", encoding="utf-8", newline="") as file_handle:
                reader = csv.reader(file_handle)
                return "\n".join(",".join(cell for cell in row) for row in reader)

        if file_path.lower().endswith(".xlsx"):
            workbook = load_workbook(file_path, read_only=True, data_only=True)
            sheet_text: list[str] = []
            for worksheet in workbook.worksheets:
                sheet_text.append(f"[Sheet: {worksheet.title}]")
                for row in worksheet.iter_rows(values_only=True):
                    values = ["" if value is None else str(value) for value in row]
                    if any(values):
                        sheet_text.append(",".join(values))
            workbook.close()
            return "\n".join(sheet_text)

        if file_path.lower().endswith(".xls"):
            workbook = xlrd.open_workbook(file_path)
            sheet_text: list[str] = []
            for worksheet in workbook.sheets():
                sheet_text.append(f"[Sheet: {worksheet.name}]")
                for row_index in range(worksheet.nrows):
                    values = [
                        "" if cell_value is None else str(cell_value)
                        for cell_value in worksheet.row_values(row_index)
                    ]
                    if any(values):
                        sheet_text.append(",".join(values))
            return "\n".join(sheet_text)

    return ""


def chunk_text(text: str, chunk_size: int = 200, overlap: int = 30) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_size]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def index_documents(study_id: str, file_paths_with_types: list[tuple[str, str]]) -> str | None:
    all_chunks: list[str] = []
    index = None
    batch_size = 32
    import gc

    model = _get_model()

    for file_path, file_type in file_paths_with_types:
        try:
            logger.info(f"Processing {file_path} for indexing...")
            extracted_text = extract_text_from_file(file_path, file_type)
            if not extracted_text:
                continue
                
            file_chunks = chunk_text(extracted_text)
            # Clear text immediately to save RAM
            del extracted_text
            gc.collect()

            if not file_chunks:
                continue

            for i in range(0, len(file_chunks), batch_size):
                batch = file_chunks[i : i + batch_size]
                embeddings = model.encode(batch, convert_to_numpy=True)
                normalized_embeddings = np.asarray(embeddings, dtype=np.float32)

                if index is None:
                    index = faiss.IndexFlatL2(normalized_embeddings.shape[1])
                
                index.add(normalized_embeddings)
            
            all_chunks.extend(file_chunks)
            gc.collect()
        except Exception as exc:
            logger.error(f"Failed to process file {file_path}: {exc}")
            continue

    if not all_chunks or index is None:
        logger.info(
            "No chunks extracted for indexing.",
            extra={
                "event_action": "rag_retrieval",
                "model_version": "all-MiniLM-L6-v2",
                "metadata": {"study_id": study_id, "chunks": 0},
            },
        )
        del model
        gc.collect()
        return None

    os.makedirs(settings.VECTOR_DIR, exist_ok=True)
    index_path = get_index_path(study_id)
    faiss.write_index(index, index_path)
    chunks_path = get_chunks_path(study_id)
    with open(chunks_path, "w", encoding="utf-8") as file_handle:
        json.dump({"study_id": study_id, "chunks": all_chunks}, file_handle)

    logger.info(f"Document index saved with {len(all_chunks)} chunks.")
    
    # Final cleanup
    del model
    del all_chunks
    del index
    gc.collect()
    
    return index_path
