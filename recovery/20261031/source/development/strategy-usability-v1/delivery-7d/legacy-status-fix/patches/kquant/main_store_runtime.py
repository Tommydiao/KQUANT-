"""Explicit startup-only concurrency preparation for the existing main store."""
from contextlib import closing
from pathlib import Path
import logging
import sqlite3


def prepare_read_concurrency(path: Path) -> dict:
    # Restored SQLite snapshots can retain DELETE mode after all migrations are
    # current. Do this once before starting workers, never in a request handler.
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=.1)) as db:
        before = str(db.execute('PRAGMA journal_mode').fetchone()[0]).lower()
        after = before
        if before != 'wal':
            after = str(db.execute('PRAGMA journal_mode=WAL').fetchone()[0]).lower()
        if after != 'wal':
            raise RuntimeError('MAIN_STORE_WAL_UNAVAILABLE')
    result = {'path': str(path), 'previous_journal_mode': before, 'journal_mode': after,
              'changed': before != after, 'business_rows_changed': False}
    logger = logging.getLogger(__name__)
    logger.log(logging.WARNING if result['changed'] else logging.INFO,
               'main_store_read_concurrency %s', result)
    return result
