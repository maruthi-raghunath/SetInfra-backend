import duckdb
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class DatabaseSession:
    _con = None

    @classmethod
    def get_connection(cls):
        if cls._con is None:
            # Open a single shared connection
            cls._con = duckdb.connect(settings.DB_PATH)
        return cls._con

def get_db():
    # Return a new cursor from the shared connection for thread safety
    return DatabaseSession.get_connection().cursor()
