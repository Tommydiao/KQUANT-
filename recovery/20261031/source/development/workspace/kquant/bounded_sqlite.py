"""Read-only SQL budgets; cancellation releases the snapshot worker for retries."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import monotonic


@contextmanager
def read_connection(path, *, seconds=1.0):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True,
                                 timeout=min(seconds, 0.1))
    deadline = monotonic() + seconds
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.set_progress_handler(lambda: monotonic() >= deadline, 1000)
        yield connection
    except sqlite3.OperationalError as exc:
        if monotonic() >= deadline and "interrupted" in str(exc).lower():
            raise TimeoutError("STATUS_QUERY_BUDGET_EXCEEDED") from exc
        raise
    finally:
        connection.set_progress_handler(None, 0)
        connection.close()
