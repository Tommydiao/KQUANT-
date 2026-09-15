import sqlite3
from decimal import localcontext
import pytest

from kquant_crypto.hybrid_offline_stream_journal import OfflineStreamJournal
from kquant_crypto.hybrid_spot_stream_contract_v12 import MockConnection, ProtocolError
from test_hybrid_spot_stream_contract_v12 import CONNECTION, EXPECTED, NOW, report, trade


def append(journal, event):
    return journal.append(event, received_at_ms=NOW+10, expected=EXPECTED)


def test_restart_and_duplicate(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    assert append(journal, report()).fill is None
    assert append(journal, trade()).fill is not None
    journal.close()
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    assert append(journal, trade()).duplicate_report
    assert journal.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 2
    journal.close()


@pytest.mark.parametrize('column', ['normalized', 'report_key'])
def test_existing_corruption_blocks_append_without_repairing_history(tmp_path,column):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, report())
    with journal.db:
        journal.db.execute(f"UPDATE events SET {column}=?", ('{}' if column=='normalized' else 'corrupt',))
    with pytest.raises(ValueError,match='integrity mismatch'):
        append(journal, trade())
    assert journal.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
    assert journal.db.execute(f'SELECT {column} FROM events').fetchone()[0] == ('{}' if column=='normalized' else 'corrupt')
    result = journal.reconcile()
    assert result['status'] == 'REQUIRES_RECONCILIATION'
    expected_reason = 'STORED_NORMALIZATION_MISMATCH' if column=='normalized' else 'STORED_REPORT_KEY_MISMATCH'
    assert expected_reason in {item['reason'] for item in result['problems']}
    journal.close()


def test_failed_commit_does_not_consume_event(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    journal.db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'fault'); END")
    with pytest.raises(sqlite3.IntegrityError):
        append(journal, trade())
    assert journal.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0
    journal.db.execute('DROP TRIGGER fail_insert')
    assert append(journal, trade()).fill is not None
    journal.close()


def test_conflict_survives_restart(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, trade())
    journal.close()
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    with pytest.raises(ProtocolError, match='CONFLICTING_EXECUTION_ID'):
        append(journal, trade(n='0.05'))
    assert journal.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
    journal.close()


def test_connection_epoch_cannot_silently_reset_dedup(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    journal.close()
    with pytest.raises(ValueError, match='Separate journal'):
        OfflineStreamJournal(tmp_path, MockConnection('synthetic://unit', 'new-epoch', 0))


def test_cumulative_total_does_not_fabricate_fill(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, report(x='CANCELED', X='CANCELED', z='0.4', Z='40'))
    result = journal.reconcile()
    assert result['orders'][0]['observed_fill_quantity'] == '0'
    assert 'CUMULATIVE_FILL_QUANTITY_MISMATCH' in result['orders'][0]['reasons']
    assert not result['account_reconciled']
    journal.close()


def test_late_fill_resolves_quantity_but_not_unconverted_commission(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, report(x='CANCELED', X='CANCELED', z='0.4', Z='40'))
    append(journal, trade())
    result = journal.reconcile()
    assert 'COMMISSION_CONVERSION_UNVERIFIED' in result['orders'][0]['reasons']
    assert 'CUMULATIVE_FILL_QUANTITY_MISMATCH' not in result['orders'][0]['reasons']
    journal.close()


def test_unknown_protocol_state_is_not_cleared_by_quantity_match(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, report(X='UNKNOWN_NEW_STATE'))
    result = journal.reconcile()
    assert result['status'] == 'REQUIRES_RECONCILIATION'
    assert 'UNSUPPORTED_ORDER_STATUS:UNKNOWN_NEW_STATE' in result['orders'][0]['reasons']
    journal.close()


def test_reconciliation_is_independent_of_ambient_decimal_precision(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, trade(l='0.123456789', z='0.123456789', Y='12.3456789', Z='12.3456789'))
    append(journal, trade(I=3, t=21, l='0.123456789', z='0.246913578', Y='12.3456789', Z='24.6913578'))
    normal = journal.reconcile()
    with localcontext() as context:
        context.prec = 3
        assert journal.reconcile() == normal
    assert normal['orders'][0]['observed_fill_quantity'] == '0.246913578'
    journal.close()


def test_normalization_corruption_reported(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, report())
    with journal.db:
        journal.db.execute("UPDATE events SET normalized='{}'")
    result = journal.reconcile()
    assert result['problems'][0]['reason'] == 'STORED_NORMALIZATION_MISMATCH'
    assert not result['execution_allowed']
    journal.close()


def test_native_commission_ledger_deduplicates_and_does_not_convert(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, trade(n='0.0001', N='BNB'))
    append(journal, trade(n='0.0001', N='BNB'))
    append(journal, trade(I=3, t=21, z='0.8', Z='80', n='0.04', N='USDT'))
    result = journal.reconcile()
    order = result['orders'][0]
    assert order['commissions_by_asset'] == {'BNB': '0.0001', 'USDT': '0.04'}
    assert order['observed_fill_quantity'] == '0.8'
    assert order['commission_coverage_complete']
    assert order['commission_valuation'] == 'NATIVE_UNITS_ONLY_NOT_CONVERTED'
    assert 'COMMISSION_CONVERSION_UNVERIFIED' in order['reasons']
    assert not result['account_reconciled']
    journal.close()
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    assert journal.reconcile() == result
    journal.close()


def test_inventory_projection_uses_persisted_fills_and_rejects_corruption(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, trade(n='0.001', N='BTC'))
    contract = dict(symbol='BTCUSDT', base_asset='BTC', quote_asset='USDT',
                    opening_base='0', locked_base='0', step_size='0.01',
                    min_quantity='0.01', min_notional='5', bid='100')
    result = journal.inventory_projection(**contract)
    assert result['projected_base'] == '0.399'
    assert result['rounded_quantity'] == '0.39'
    assert not result['account_reconciled']
    with journal.db:
        journal.db.execute("UPDATE events SET normalized='{}'")
    with pytest.raises(ValueError, match='inventory blocked'):
        journal.inventory_projection(**contract)
    journal.close()
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    with pytest.raises(ValueError, match='inventory blocked'):
        journal.inventory_projection(**contract)
    journal.close()


def test_inventory_blocks_missing_fill_even_if_partial_balance_meets_minimum(tmp_path):
    journal = OfflineStreamJournal(tmp_path, CONNECTION)
    append(journal, trade(n='0', N=None))
    append(journal, report(I=3, x='CANCELED', X='CANCELED', z='0.8', Z='80'))
    result = journal.inventory_projection(symbol='BTCUSDT', base_asset='BTC', quote_asset='USDT',
        opening_base='0', locked_base='0', step_size='.01', min_quantity='.01', min_notional='5', bid='100')
    assert result['rounded_quantity'] is None
    assert not result['minimum_filters_satisfied']
    assert 'CUMULATIVE_FILL_QUANTITY_MISMATCH' in result['reconciliation_blockers']
    journal.close()
