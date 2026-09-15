"""M1 component contract using unchanged baseline protection code and fixtures."""

from concurrent.futures import Future

from test_candidate_portfolio import warm_states, warmed, trigger


def test_btc_protection_needs_no_sol_batch_or_finished_model(warm_states):
    portfolio=warmed(warm_states,execution='quotes')
    at=trigger(portfolio,symbols=('BTCUSDT',))
    portfolio.on_quote('BTCUSDT',364.9,365,at+1,sequence=1)
    assert 'BTCUSDT' in portfolio.positions
    model=Future()
    portfolio.exits['BTCUSDT']='timeout'
    # No quote: retain the position. Never fabricate its execution price.
    assert not portfolio.trades
    # Independent BTC quote consumes the original protection routine without
    # waiting on either a SOL bar or the unresolved model future.
    portfolio.accept_entries=False
    portfolio.on_quote('BTCUSDT',364.8,365,at+2,sequence=2)
    assert not model.done()
    assert 'BTCUSDT' not in portfolio.positions
    assert len(portfolio.trades)==1
    assert portfolio.trades[0]['exit_market_reference']==364.8
    assert portfolio.trades[0]['exit_reason']=='timeout'
    assert 'SOLUSDT' not in portfolio.last_quotes
