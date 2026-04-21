from fastapi import HTTPException


def api_error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": error_code, "message": message},
    )
