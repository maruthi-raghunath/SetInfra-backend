import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.endpoints import auth, chats, files, health, query, studies
from app.core.compression import warm_schema_cache
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.db_init import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.VECTOR_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
    init_db()
    warm_schema_cache(settings.DB_PATH)
    yield


app = FastAPI(title="Setinfra API", lifespan=lifespan)

# Add CORS Middleware to allow requests from the React frontend running on port 3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For prototype, allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(studies.router, prefix="/api/studies", tags=["studies"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(chats.router, prefix="/api/chats", tags=["chats"])
app.include_router(query.router, prefix="/api/query", tags=["query"])


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    if isinstance(exc.detail, dict) and "error_code" in exc.detail and "message" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": "HTTP_ERROR", "message": str(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    response = await request_validation_exception_handler(request, exc)
    return JSONResponse(
        status_code=400,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "details": response.body.decode("utf-8"),
        },
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
