# Prepare Live Facts, Persist With Accepted Calculation

Development only, not the accepted1984 source or frozen b874/75a0 payload.
The b874 assembly stopped after914.985s because its direct preflight-style quote
generator hit the shared300ms journal guard. Production preflight already catches
this and retries captured quotes; this does not prove a fatal production exit.

The live reference-refresh path can prepare the same hashed facts without that
redundant pre-admission write. The durable calculation journal retains inputs;
accepted CAS result commit persists facts and evaluations in the same transaction.
Prewarm keeps its existing persistent/bounded-retry path. Source semantics,
fact validity, original checkpoints and deadline are unchanged.

The assembly must explicitly exercise live preparation AND guarded prewarm retry;
changing only a test driver's exception handling is not a production repair.
