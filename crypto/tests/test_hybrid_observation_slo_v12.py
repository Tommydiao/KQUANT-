import tempfile
from pathlib import Path
import unittest
from kquant_crypto.hybrid_observation_slo_v12 import ObservationSLO


class SLOTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.path=Path(self.t.name)/'slo.sqlite3';self.start=1788603800.
        self.s=ObservationSLO(self.path,window_start=self.start,window_end=self.start+100,registered_before=self.start-1,policy_hash='a'*64)
    def tearDown(self):self.s.close();self.t.cleanup()
    def quote(self,symbol,offset=0):
        t=self.start+offset
        return dict(symbol=symbol,market_type='spot',stream=symbol.lower()+'@ticker',source_event_time_native_ms=int(t*1000),
                    source_time=t,received_at_lower=t+.1,received_at_upper=t+.5,bid=100.,ask=101.,bid_size=1.,ask_size=1.,
                    clock_segment_id='clock',source_event_time_modified=False)
    def test_full_window_not_message_count_and_no_future_availability(self):
        for s in ('BTCUSDT','ETHUSDT','SOLUSDT'):self.s.record(s,self.quote(s))
        r=self.s.report(observed_until=self.start+10)
        self.assertAlmostEqual(r['all_symbols']['fraction'],.095)
        self.assertFalse(r['window_complete']);self.assertFalse(r['G3_passed'])
    def test_missing_coin_and_protection_separate(self):
        self.s.record('btc',self.quote('BTCUSDT'))
        r=self.s.report(observed_until=self.start+100)
        self.assertEqual(r['all_symbols']['fraction'],0)
        self.assertIsNone(r['protection_availability'])
        self.assertAlmostEqual(r['per_symbol']['BTCUSDT']['qualified_seconds'],29.5)
    def test_restart_dedup_and_immutable_denominator(self):
        q=self.quote('BTCUSDT');self.s.record('q',q)
        self.s.close();self.s=ObservationSLO(self.path,window_start=self.start,window_end=self.start+100,registered_before=self.start-1,policy_hash='a'*64)
        self.assertFalse(self.s.record('q',q))
        q['ask']=102.
        with self.assertRaises(ValueError):self.s.record('q',q)
        with self.assertRaises(ValueError):ObservationSLO(self.path,window_start=self.start,window_end=self.start+10,registered_before=self.start-1,policy_hash='a'*64)
    def test_out_of_order_same_result(self):
        self.s.record('late',self.quote('BTCUSDT',50));self.s.record('early',self.quote('BTCUSDT'))
        self.assertAlmostEqual(self.s.report(observed_until=self.start+100)['per_symbol']['BTCUSDT']['qualified_seconds'],59.)
    def test_preregistration_after_start_rejected(self):
        with self.assertRaises(ValueError):ObservationSLO(self.path,window_start=self.start,window_end=self.start+10,registered_before=self.start+1,policy_hash='a'*64)

    def test_receipt_counts_exclude_outside_window_but_keep_valid_overlap(self):
        self.s.record('old',self.quote('BTCUSDT',-10))
        self.s.record('inside',self.quote('BTCUSDT',40))
        self.s.record('end',self.quote('BTCUSDT',99.5))
        self.s.record('future',self.quote('BTCUSDT',110))
        r=self.s.report(observed_until=self.start+100)
        self.assertEqual(r['counts']['BTCUSDT'],{'accepted':1,'rejected':0})
        self.assertAlmostEqual(r['per_symbol']['BTCUSDT']['qualified_seconds'],49.5)
        self.assertEqual(r['count_scope'],'RECEIPTS_IN_HALF_OPEN_OBSERVED_WINDOW')


if __name__=='__main__':unittest.main()
