import duckdb
import os
import json
import sys
sys.path.append('/app')
from app.core.compression import get_cached_schema, count_tokens, warm_schema_cache

warm_schema_cache('/app/data/db/setinfra.db')
study_id = '9fbdc7c1-57c7-4f32-b1b3-ef7619497989'

con = duckdb.connect('/app/data/db/setinfra.db', read_only=True)
paths = con.execute("SELECT storage_path FROM files WHERE study_id = ? AND file_type = 'SDTM_CSV'", (study_id,)).fetchall()
con.close()

original_tokens = 0
for (path,) in paths:
    if path and os.path.exists(path):
        size = os.path.getsize(path)
        original_tokens += int(size / 4)

schema = get_cached_schema(study_id)
actual_tokens = int(count_tokens(json.dumps(schema))) if schema else 0

savings = 0.0
if original_tokens > 0:
    savings = round(((original_tokens - actual_tokens) / original_tokens) * 100, 2)

print(f"Original: {original_tokens}, Actual: {actual_tokens}, Savings: {savings}%")
