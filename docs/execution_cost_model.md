# Execution Cost Model

Historical replay now records optimistic, baseline, and conservative execution
scenarios. Each scenario applies commission and slippage per side, then raises
slippage for low-priced or low-dollar-volume symbols. The baseline result remains
the primary existing replay outcome; scenario results are attached for audit and
comparison.

This is an execution-cost assumption model, not a broker feed or a guarantee of
fillable prices. It does not create positions, read an account, or submit orders.
