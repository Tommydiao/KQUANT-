import pytest
from kquant_crypto.hybrid_public_rule_index import PublicRuleIndex
from kquant_crypto.hybrid_rule_archive import save_snapshot


def snapshot(path,t,status='TRADING'):
    return save_snapshot(path,{'symbols':[{'symbol':'BTCUSDT','status':status}]},
                         received_at=t,source='BINANCE_SPOT_PUBLIC_EXCHANGE_INFO')


def test_restore_ordering_dedup_and_staleness(tmp_path):
    archive=tmp_path/'archive'
    older,newer=snapshot(archive,10),snapshot(archive,20)
    idx=PublicRuleIndex(tmp_path/'index',archive)
    idx.register(newer)
    idx.register(older)
    idx.register(newer)
    idx.close()
    idx=PublicRuleIndex(tmp_path/'index',archive)
    result=idx.latest('BTCUSDT',now_ms=21,max_age_ms=5)
    assert result['digest']==newer and not result['execution_allowed']
    assert idx.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==2
    with pytest.raises(ValueError,match='stale or future'):
        idx.latest('BTCUSDT',now_ms=15,max_age_ms=5)
    with pytest.raises(ValueError,match='stale or future'):
        idx.latest('BTCUSDT',now_ms=30,max_age_ms=5)
    idx.close()


def test_conflict_and_corrupt_archive_do_not_silently_refresh(tmp_path):
    archive=tmp_path/'archive'
    first=snapshot(archive,10)
    conflict=snapshot(archive,10,'BREAK')
    idx=PublicRuleIndex(tmp_path/'index',archive)
    idx.register(first)
    with pytest.raises(ValueError,match='Conflicting'):
        idx.register(conflict)
    (archive/(first+'.json')).write_text('{}')
    with pytest.raises(ValueError,match='integrity'):
        idx.latest('BTCUSDT',now_ms=10,max_age_ms=5)
    idx.close()
