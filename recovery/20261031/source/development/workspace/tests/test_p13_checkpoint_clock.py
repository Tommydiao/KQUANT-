from contextlib import closing
from datetime import UTC,date,datetime,timedelta
import json
import time

from kquant import options_opening_momentum_journal as journal
from kquant.options_opening_trend_runtime import TrendLane
from kquant.options_opening_trend_store import initialize
from kquant.options_one_minute import initialize as minute_initialize
from kquant.options_data_paths import connect_store

DAY=date(2026,10,13)
OPEN=datetime(2026,10,13,13,30,tzinfo=UTC)
SCOPE='TEST_ONLY_CLOCK_SCOPE'


def registered():
    return [{'symbol':('GWH' if i==99 else 'TEST'+str(i)),'identity_status':'verified'} for i in range(100)]+[
        {'symbol':'UNKNOWN'+str(i),'identity_status':'identity_unconfirmed'} for i in range(11)]


def test_manifest_positions_exist_before_any_bar_and_keep_deadlines(tmp_path):
    path=tmp_path/'TEST_ONLY-opening.sqlite3'
    initialize(path)
    journal.initialize(path)
    result=journal.register_clock_positions(path,registered(),DAY,SCOPE,OPEN-timedelta(minutes=30))
    assert result['inserted']==500
    assert journal.register_clock_positions(path,registered(),DAY,SCOPE,OPEN)['inserted']==0
    with closing(connect_store(path)) as db:
        rows=db.execute('SELECT state,deadline_at FROM two_hour_jobs WHERE symbol=? ORDER BY slot',('GWH',)).fetchall()
    assert [row[0] for row in rows]==['WAIT_CLOCK']*5
    deadlines=[row[1] for row in rows]
    journal.advance_clock_positions(path,registered(),DAY,SCOPE,OPEN+timedelta(minutes=5))
    with closing(connect_store(path)) as db:
        assert db.execute('SELECT state FROM two_hour_jobs WHERE symbol=? AND slot=?',('GWH','1')).fetchone()[0]=='WAIT_INPUT'
    journal.advance_clock_positions(path,registered(),DAY,SCOPE,OPEN+timedelta(minutes=30))
    with closing(connect_store(path)) as db:
        rows=db.execute('SELECT state,reason,deadline_at FROM two_hour_jobs WHERE symbol=? ORDER BY slot',('GWH',)).fetchall()
    assert all(row[:2]==('EXPIRED','DATA_UNAVAILABLE_NO_MINUTE') for row in rows)
    assert deadlines==[row[2] for row in rows]


def test_late_registration_never_creates_elapsed_history(tmp_path):
    path=tmp_path/'TEST_ONLY-opening.sqlite3'
    initialize(path)
    journal.initialize(path)
    assert journal.register_clock_positions(path,registered(),DAY,SCOPE,OPEN+timedelta(minutes=30))['inserted']==0
    with closing(connect_store(path)) as db:
        assert db.execute('SELECT COUNT(*) FROM two_hour_jobs').fetchone()[0]==0


def test_real_lane_without_bar_has_durable_wait_and_terminal(tmp_path):
    minute=tmp_path/'TEST_ONLY-epoch'/'minute.sqlite3'
    minute.parent.mkdir()
    minute_initialize(minute)
    path=tmp_path/'TEST_ONLY-research'/'opening.sqlite3'
    path.parent.mkdir()
    now=[OPEN-timedelta(minutes=1)]
    class Hub:
        def publish(self,value):
            pass
    lane=TrendLane(minute,Hub(),path=path,clock=lambda:now[0])
    row=[{'symbol':'GWH','identity_status':'verified'}]
    try:
        lane.recover_registered(row,DAY,SCOPE)
        for slot in range(1,6):
            now[0]=OPEN+timedelta(minutes=slot*5,seconds=.1)
            lane.tick_registered(row,DAY,SCOPE,now[0])
            expiry=time.monotonic()+3
            while time.monotonic()<expiry:
                with closing(connect_store(path)) as db:
                    state=db.execute('SELECT state FROM two_hour_jobs WHERE symbol=? AND slot=?',('GWH',str(slot))).fetchone()[0]
                    if state=='WAIT_INPUT' and db.execute('SELECT COUNT(*) FROM evaluations WHERE symbol=?',('GWH',)).fetchone()[0]>=slot*2:
                        break
                time.sleep(.02)
            else:
                raise AssertionError(lane.state)
        now[0]=OPEN+timedelta(minutes=30)
        lane.tick_registered(row,DAY,SCOPE,now[0])
        with closing(connect_store(path)) as db:
            jobs=db.execute("SELECT state,reason FROM two_hour_jobs WHERE symbol=? AND json_extract(payload_json,'$.kind')=? ORDER BY slot",('GWH',journal.KIND)).fetchall()
            evaluations=db.execute('SELECT payload_json FROM evaluations WHERE symbol=?',('GWH',)).fetchall()
        assert len(jobs)==5 and all(row==('EXPIRED','DATA_UNAVAILABLE_NO_MINUTE') for row in jobs)
        assert len(evaluations)==10
        assert all(json.loads(raw)['state']=='INCOMPLETE' for raw, in evaluations)
    finally:
        lane.close()
