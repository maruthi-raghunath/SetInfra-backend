class QueryEngineError(Exception):
    """Base exception for query engine service failures."""


class QueryPlanError(QueryEngineError):
    def __init__(self, message: str, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


class SQLGuardrailError(QueryEngineError):
    pass


class RowLimitError(QueryEngineError):
    pass


class ExplanationError(QueryEngineError):
    pass


class AuditLogError(QueryEngineError):
    pass
