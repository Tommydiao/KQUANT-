"""Independent local health transition journal; never sends notifications."""
import json
import sqlite3
from pathlib import Path

from .hybrid_health_contract import summarize_health


class HealthJournal:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / 'hybrid_health.sqlite3', timeout=2)
        self.db.execute('CREATE TABLE IF NOT EXISTS health_samples ('
                        'id INTEGER PRIMARY KEY, observed_at INTEGER NOT NULL, '
                        'report TEXT NOT NULL, changed INTEGER NOT NULL)')
        self.db.commit()

    def append(self, observations, *, now, max_age):
        report = summarize_health(observations, now=now, max_age=max_age)
        encoded = json.dumps(report, sort_keys=True, separators=(',', ':'))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous = self.db.execute('SELECT id,observed_at,report FROM health_samples '
                                       'ORDER BY id DESC LIMIT 1').fetchone()
            if previous and now < previous[1]:
                raise ValueError('Observation clock moved backward; new clock segment required')
            if previous and now == previous[1]:
                if encoded != previous[2]:
                    raise ValueError('Conflicting observation at same time')
                self.db.commit()
                return {'sample_id': previous[0], 'inserted': False, 'changed': False}
            changed = previous is None or json.loads(previous[2])['material_state_hash'] != report['material_state_hash']
            cursor = self.db.execute('INSERT INTO health_samples(observed_at,report,changed) VALUES(?,?,?)',
                                     (now, encoded, int(changed)))
            self.db.commit()
            return {'sample_id': cursor.lastrowid, 'inserted': True, 'changed': changed}
        except BaseException:
            self.db.rollback()
            raise

    def close(self):
        self.db.close()
