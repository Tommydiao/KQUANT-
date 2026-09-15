"""Cost sensitivity on fixed historical proxy fills, not a portfolio replay."""
import math
from .hybrid_entry_attribution import cost_bridge


def reprice_fixed_fill(trade, multiplier):
    if multiplier not in (1,2) or trade['cost_multiplier']!=1 or trade['execution_source']!='ohlcv':
        raise ValueError('BASE OHLC fills and registered cost scenarios only')
    bridge=cost_bridge(trade)
    if trade.get('path_unverifiable'):
        raise ValueError('Unverifiable fill cannot be cost evidence')
    fee=trade['fee_bps']/10000*multiplier
    slip=trade['ohlcv_execution_cost_bps']/10000*multiplier
    if not 0<=fee<1 or not 0<=slip<1:raise ValueError('Invalid costs')
    q=trade['quantity'];entry=trade['entry_market_reference']*(1+slip);exit=trade['exit_market_reference']*(1-slip)
    fees=q*(entry+exit)*fee
    net=q*(exit-entry)-fees
    if multiplier==1 and not math.isclose(net,trade['net_pnl'],abs_tol=1e-7):
        raise ValueError('BASE cost parity failed')
    return dict(trade_id=trade['trade_id'],symbol=trade['symbol'],mode=trade['mode'],
        entry_time=trade['entry_time'],exit_time=trade['exit_time'],quantity=q,
        cost_multiplier=multiplier,fees=fees,net_pnl=net,base_risk_cash=bridge['base_risk_cash'],
        net_base_r=net/bridge['base_risk_cash'],portfolio_replay=False,
        quantity_and_timing_frozen=True)


def summary(rows):
    result={'trades':len(rows)}
    for name in ('net_pnl','net_base_r'):
        values=[r[name] for r in rows];wins=[v for v in values if v>0];losses=[-v for v in values if v<0]
        result[name]=dict(total=sum(values),mean=sum(values)/len(values) if values else None,
            profit_factor=sum(wins)/sum(losses) if losses else None,
            payoff=(sum(wins)/len(wins))/(sum(losses)/len(losses)) if wins and losses else None)
    return result
