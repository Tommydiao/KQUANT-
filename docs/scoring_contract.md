# Scoring Contract

`kquant.scoring.CANONICAL_SCORING_CONFIG` holds every score weight, cap, and
risk deduction used by `swing_long_v1.1.0`. `calculate_score_components` stores
the individual trend/trigger factors, risk deductions, component scores, and
total score in each signal's `score_breakdown`.

The golden sample in `tests/test_scoring.py` locks the configured arithmetic.
Changing any scoring value requires a new strategy version and updated golden
expectation; historical records remain tied to their prior configuration hash.
