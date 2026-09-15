"""Persistent index of public rule observations, never an execution cache."""
from pathlib import Path
import sqlite3
from .hybrid_rule_archive import read_snapshot


class PublicRuleIndex:
    def __init__(self, directory, archive):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        self.archive=Path(archive)
        self.db=sqlite3.connect(directory/'public_rule_index.sqlite3',timeout=2)
        self.db.execute('CREATE TABLE IF NOT EXISTS observations('
                        'symbol TEXT NOT NULL, receipt INTEGER NOT NULL, digest TEXT NOT NULL,'
                        'PRIMARY KEY(symbol,receipt))')
        self.db.commit()

    def register(self,digest):
        record=read_snapshot(self.archive,digest)
        if record.get('source')!='BINANCE_SPOT_PUBLIC_EXCHANGE_INFO' or record.get('execution_allowed') is not False:
            raise ValueError('Public observation required')
        at=record['received_at']
        if type(at) is not int or at<0:
            raise ValueError('Receipt required')
        symbols=[item['symbol'] for item in record['payload']['symbols']]
        if not symbols or any(type(s) is not str or not s for s in symbols) or len(set(symbols))!=len(symbols):
            raise ValueError('Unique explicit symbols required')
        with self.db:
            for symbol in symbols:
                old=self.db.execute('SELECT digest FROM observations WHERE symbol=? AND receipt=?',(symbol,at)).fetchone()
                if old and old[0]!=digest:
                    raise ValueError('Conflicting same-receipt rules')
                self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?)',(symbol,at,digest))

    def latest(self,symbol,*,now_ms,max_age_ms):
        if type(now_ms) is not int or now_ms<0 or type(max_age_ms) is not int or max_age_ms<0:
            raise ValueError('Explicit local observation clock required')
        row=self.db.execute('SELECT receipt,digest FROM observations WHERE symbol=? ORDER BY receipt DESC LIMIT 1',(symbol,)).fetchone()
        if not row:
            raise ValueError('Rules unavailable')
        if not 0<=now_ms-row[0]<=max_age_ms:
            raise ValueError('Rules stale or future; no fallback to old version')
        record=read_snapshot(self.archive,row[1])
        if record['received_at']!=row[0] or symbol not in [s['symbol'] for s in record['payload']['symbols']]:
            raise ValueError('Index and archive disagree')
        return {'digest':row[1],'received_at':row[0],
                'clock_unit':'MILLISECONDS',
                'clock_scope':'LOCAL_RECEIPT_NOT_EXCHANGE_AVAILABILITY',
                'execution_allowed':False,'account_verified':False}

    def close(self):
        self.db.close()
