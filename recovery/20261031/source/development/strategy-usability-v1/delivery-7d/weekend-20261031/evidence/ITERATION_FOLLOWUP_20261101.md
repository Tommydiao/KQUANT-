# November1 isolated implementation follow-up

Original seven-day FAIL and November delivery dates are unchanged.

Implemented a bounded2048-entry immutable five-minute aggregation cache,
using the original price_aggregate function after current complete_minutes
admission. Exact minute content and function identity key the cache; mutable
inputs bypass it. Missing/conflicting inputs still cannot use a computed block.
Eleven-prefix unit verification reduces66 original block aggregations to11,
without changing values/hashes. This is not measured whole-runtime acceleration.

Removed three runtime imports of assembly.bootstrap. Exact parent modules are
now named imports selected by the assembly source mapping.205 code files were
materialized in a temporary directory and imported with test bootstrap forbidden.
Temporary source files were cleaned. No business databases were materialized.
This closes the direct runtime dependency, not production-entry acceptance.

171 affected tests passed. Actual independent backend/Gateway/browser short6
finished240.156seconds with507/507 background reads, zero read deadlines,
and9 HTTP failures linked to the declared crash by request/process evidence.
Each strategy accounts for2200 positions; predeclared AAPL exceptions remain.
Last first-full P95=14.750s, admission queueP95=13.312s: limited performance FAIL.
No matching hour or release acceptance request is justified yet.

No production restart, accepted-code edit, business-data mutation, SDK connection
or paid API request. Only isolated8193/8194 were used. All results are TEST_ONLY,
not live-window computation, natural opportunity, or qualified-to-page evidence.

Remaining: admission repeat/epoch churn and batch persistence bottleneck,
accurate deployable manifest/actual-entry assembly, research_review_v2,
authorized launch/fee renewal and real observation windows. No background coding
is promised after the session; RESUME.md is the continuation pointer.
