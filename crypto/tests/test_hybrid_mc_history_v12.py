import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from kquant_crypto.hybrid_mc_history_v12 import load_authorized,bounded_rows,AUTHORIZED_END


class MCHistoryTests(unittest.TestCase):
    def test_unauthorized_interval_rejected_before_read(self):
        with patch('kquant_crypto.hybrid_mc_history_v12.sha') as digest:
            for start,end in [(AUTHORIZED_END,AUTHORIZED_END+300),(0,300),(AUTHORIZED_END-60*86400,AUTHORIZED_END)]:
                with self.assertRaises(ValueError):load_authorized(Path.cwd(),start=start,end=end)
            digest.assert_not_called()

    def test_future_price_changes_not_materialized(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bars.parquet'
            def write(future):
                rows=[dict(start=t,open=v,high=v,low=v,close=v,volume=1.,available_at=t+300,
                           availability_basis='assumed_close_historical_replay') for t,v in [(300,1.),(600,2.),(900,future)]]
                pq.write_table(pa.Table.from_pylist(rows),p)
            write(999.)
            old=bounded_rows(p,300,900)
            write(-999.)
            self.assertEqual(old,bounded_rows(p,300,900))
            self.assertEqual([r['start'] for r in old],[300,600])


if __name__=='__main__':unittest.main()
