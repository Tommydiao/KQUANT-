# Forward Pilot And Paper Simulation Protocol

## Preconditions

Forward observation can start only when KQUANT has:

- a frozen strategy manifest tied to a reviewed validation fingerprint;
- a fixed universe snapshot hash;
- an explicit start date and `paper_observation` mode; and
- a record that real money is not allowed.

The pilot stores a preflight, exact candidate queue, data status, veto status,
manual plan snapshot, close notes, and later outcome. It cannot modify frozen
strategy parameters or silently replace the universe.

## Daily Routine

1. Run preflight and record the data/operational result.
2. Run the stock scan manually and save its candidate queue before outcomes are known.
3. Record whether each candidate triggered, was skipped, invalidated, stopped,
   hit target, or exited by time.
4. Save closing notes and data incidents.

Only system failures, data faults, and display bugs may be repaired during the
observation period. A strategy parameter change requires a new version and a
new pilot session.

## Paper Simulation

Paper simulation is a separate cash-only ledger. Its limits are enforced by
code: risk per trade at or below 0.25%, finite maximum positions and daily
risk, no averaging, no chase above planned entry high, and no leverage.

Every simulated entry references a forward candidate. Every exit is a
human-recorded simulated price. Neither operation reads a brokerage account,
places an order, or claims to be a real fill.

## Evidence Threshold

The Go/No-Go evaluator requires at least 15 forward market days, traceable
candidates, no material data incidents, positive and sufficient historical
evidence, conservative-cost evidence, paper results, user-discipline review,
and intact security boundaries. Missing evidence produces `NO_GO`.
