# Strategy Lifecycle Policy

## Current decision policy

`swing_long_v1` is the only selectable KQUANT decision strategy. Its immutable
configuration is registered as `swing_long_v1.1.0` and its rules are defined in
`docs/strategy_specification.md`.

## Legacy profiles

Earlier profile names remain loadable only to preserve historic reports,
journals, and comparison experiments. Their lifecycle is
`legacy_comparison_only`; they are removed from the visible strategy selector
and cannot be mistaken for the current production decision policy.

Legacy evidence remains separately versioned. It must not be combined with
`swing_long_v1` results or used to loosen the canonical strategy's gates.
