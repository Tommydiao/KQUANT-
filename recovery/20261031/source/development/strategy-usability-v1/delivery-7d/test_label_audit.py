"""Selection tests only; fixture outcomes are never real-market evidence."""
import unittest
from label_recorded_events import first_events


def event(identity, evaluated, *, symbol='A', deadline='2026-10-16T13:40:00Z', state='NUMERIC_PASS'):
    return dict(evaluation_id=identity, symbol=symbol, right='CALL', state=state,
        calculation_bar_end='2026-10-16T13:35:00Z', evaluated_at=evaluated, deadline_at=deadline)


class RecordedEventSelection(unittest.TestCase):
    def test_first_timely_event_not_best_later_revision(self):
        late_revision = event('later', '2026-10-16T13:35:20Z')
        first = event('first', '2026-10-16T13:35:10Z')
        self.assertEqual(first_events([late_revision, first], ['A']), [first])

    def test_deadline_and_precheckpoint_are_not_timely(self):
        rows = [event('before', '2026-10-16T13:34:59Z'), event('at', '2026-10-16T13:40:00Z'),
            event('after', '2026-10-16T13:40:01Z')]
        self.assertEqual(first_events(rows, ['A']), [])

    def test_incomplete_or_unregistered_not_promoted(self):
        rows = [event('unknown', '2026-10-16T13:35:01Z', symbol='UNKNOWN'),
            event('incomplete', '2026-10-16T13:35:02Z', state='INCOMPLETE')]
        self.assertEqual(first_events(rows, ['A']), [])


if __name__ == '__main__':
    unittest.main()
