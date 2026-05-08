FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed for compiling duckdb or evaluating FAISS if necessary
RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Using uvicorn to run the fastAPI app dynamically binding to PORT (required by Render/Cloud hosts), defaulting to 8000 locally
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1

