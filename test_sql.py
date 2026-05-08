import duckdb
con = duckdb.connect('/app/data/db/setinfra.db', read_only=True)
print(con.execute("SELECT sql_executed, prompt_trace FROM audit_logs WHERE prompt_trace LIKE '%overlay%' LIMIT 1").fetchall())
