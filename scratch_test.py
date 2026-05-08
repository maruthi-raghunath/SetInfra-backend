import json
import sys
from pathlib import Path
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")
study_ids = [
    'd98d8914-62df-44af-bffc-4c250162e352', 
    '340bd10f-99f9-4b01-b0e5-d85433738e5e', 
    '9fbdc7c1-57c7-4f32-b1b3-ef7619497989'
]
vector_dir = Path("./data/vector")

query = "Summarize the inclusion criteria of the study"
query_emb = model.encode([query], convert_to_numpy=True)
query_emb = np.asarray(query_emb, dtype=np.float32)

for study_id in study_ids:
    chunks_path = vector_dir / f"{study_id}.chunks.json"
    index_path = vector_dir / f"{study_id}.index"
    if not chunks_path.exists():
        continue
    with open(chunks_path, 'r', encoding='utf-8') as f:
        chunks = json.load(f)["chunks"]
    print(f"Study: {study_id}, Total chunks: {len(chunks)}")
    
    # search for section 3.3.2 or inclusion criteria
    found = []
    for i, chunk in enumerate(chunks):
        if "3.3.2" in chunk or "inclusion" in chunk.lower():
            found.append((i, chunk))
    
    if found:
        print(f"Found {len(found)} chunks with '3.3.2' or 'inclusion criteria':")
        for i, c in found[:5]: # print first 5
            print(f"  [{i}]: {c[:100]}...")
            
    if index_path.exists():
        index = faiss.read_index(str(index_path))
        D, I = index.search(query_emb, 100) # get top 100
        print(f"Top 5 FAISS indices: {I[0][:5]}")
        print(f"Distances: {D[0][:5]}")
        
        # Check if any of the 'found' chunks are in the top 100
        for i, _ in found:
            if i in I[0]:
                rank = list(I[0]).index(i)
                print(f"  Chunk {i} is at rank {rank} (Distance: {D[0][rank]})")
            else:
                print(f"  Chunk {i} is NOT in top 100!")
                
    print("-" * 50)
