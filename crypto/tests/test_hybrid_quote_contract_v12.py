import copy
import unittest
from kquant_crypto.hybrid_quote_contract_v12 import describe_quote, covered_seconds


class QuoteContractTests(unittest.TestCase):
    def quote(self):
        return dict(symbol='BTCUSDT',market_type='spot',stream='btcusdt@ticker',
                    source_event_time_native_ms=1788603833796,source_time=1788603833.796,
                    received_at_lower=1788603833.852,received_at_upper=1788603834.44,
                    bid=100.,ask=101.,bid_size=2.,ask_size=1.,clock_segment_id='segment',
                    source_event_time_modified=False)

    def test_sample_does_not_mean_price_change_or_exchange_fill(self):
        q=self.quote(); original=copy.deepcopy(q); result=describe_quote(q)
        self.assertTrue(result['eligible_sample'])
        self.assertFalse(result['strict_price_change_evidence'])
        self.assertFalse(result['exchange_execution_evidence'])
        self.assertEqual(q,original)

    def test_bookticker_not_upgraded_with_server_clock(self):
        q=self.quote(); q.pop('source_event_time_native_ms'); q['stream']='btcusdt@bookTicker'
        self.assertFalse(describe_quote(q)['eligible_sample'])

    def test_units_receipt_order_and_size(self):
        for field,value in [('source_event_time_native_ms',1788603833796000),
                            ('received_at_lower',1788603500.),('ask_size',0),('bid',float('nan'))]:
            q=self.quote(); q[field]=value
            self.assertFalse(describe_quote(q)['eligible_sample'])

    def test_time_denominator_not_messages(self):
        self.assertEqual(covered_seconds([(10,20),(15,25),(10,20)],0,100)['fraction'],.15)
        self.assertEqual(covered_seconds([],0,100)['fraction'],0)
        with self.assertRaises(ValueError): covered_seconds([],0,0)


if __name__=='__main__': unittest.main()
