"""Isolated append-only retrospective reviews, with no account or fill schema."""
import hashlib
import json


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class ResearchReviewStore:
    TABLES = {'research_review_runs', 'research_reviews'}

    def __init__(self, connection):
        self.db = connection
        tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables - self.TABLES:
            raise ValueError('Refusing non-research database before any schema writes')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS research_review_runs (
                run_id TEXT PRIMARY KEY, manifest TEXT NOT NULL,
                scope TEXT NOT NULL CHECK(scope='DEV_ONLY'), recorded_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_reviews (
                run_id TEXT NOT NULL REFERENCES research_review_runs(run_id),
                review_id TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                PRIMARY KEY(run_id,review_id));
        ''')

    def ingest(self, run_id, manifest, reviews, *, recorded_at):
        if not run_id or not recorded_at or manifest.get('scope') != 'DEV_ONLY':
            raise ValueError('Explicit development identity required')
        prepared = []
        identities = set()
        for review in reviews:
            if (review.get('scope') != 'DEV_ONLY' or review.get('decision') != 'ABSTAIN'
                    or review.get('review_kind') != 'RETROSPECTIVE_COMPATIBILITY_AUDIT_NOT_HISTORICAL_DECISION'
                    or review.get('usable_prediction') is not None
                    or any(review.get(field) is not False for field in (
                        'allowed_formal_eval', 'allowed_alert', 'allowed_paper', 'allowed_shadow',
                        'allowed_sizing', 'allowed_execution', 'formal_gate_changed'))):
                raise ValueError('Only non-executable retrospective reviews allowed')
            identity = review['review_id']
            if identity in identities:
                raise ValueError('Duplicate review in input batch')
            identities.add(identity)
            payload = encoded(review)
            prepared.append((identity, payload, hashlib.sha256(payload.encode()).hexdigest()))
        body = encoded(manifest)
        self.db.execute('BEGIN IMMEDIATE')
        inserted = 0
        try:
            old = self.db.execute('SELECT manifest FROM research_review_runs WHERE run_id=?', (run_id,)).fetchone()
            if old and old[0] != body:
                raise ValueError('Run manifest changed; use a new version/run')
            if not old:
                self.db.execute('INSERT INTO research_review_runs VALUES(?,?,?,?)',
                                (run_id, body, 'DEV_ONLY', recorded_at))
            for identity, payload, digest in prepared:
                old = self.db.execute('SELECT payload,payload_hash FROM research_reviews WHERE run_id=? AND review_id=?',
                                      (run_id, identity)).fetchone()
                if old:
                    if tuple(old) != (payload, digest):
                        raise ValueError('Immutable review changed; use a new run')
                else:
                    self.db.execute('INSERT INTO research_reviews VALUES(?,?,?,?)', (run_id, identity, payload, digest))
                    inserted += 1
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return {'inserted': inserted, 'idempotent': len(prepared) - inserted,
                'scope': 'DEV_ONLY', 'execution_enabled': False}
