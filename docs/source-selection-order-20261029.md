# Evidence selection order — 2026-10-29

## Reproduced mechanism

Bounded per-query and per-part lanes could spend slots on candidates before
the final requested-court/regime filter. Dropping those candidates afterwards
does not recover the relevant candidate already outside the slot limit.
Decision slots were also ordered by section priority without a topic-first
preference: an unrelated high-rank record could occupy a limited slot ahead
of relevant unlabelled reasoning. This is a selection issue, not proof that
the underlying corpus is missing or incorrect.

## Changes

- Apply existing explicit court/regime constraints before lane limits.
- Stably prefer actual-text relevance in each query lane and per-part lane.
- Rank decision positions by text relevance, then section priority, then
  existing retrieval score. Preserve statute/document positions.
- Keep unknown-topic candidates as lower-priority candidates rather than
  deleting them; verified-only admission and semantic claim checks remain.
- Regression fixtures cover wrong court before a one-slot cutoff, unrelated
  high-rank decisions, weak statute candidates, unchanged input lists, and
  repair-seed invalidation when the source view changes.

## Measurement scope

Synthetic local selection benchmark: 96 verified candidate fixtures, 48
intermediate slots, 8 final slots, 20 repeats. Median 7.28 ms, maximum 335.48
ms including the first invocation/lazy imports. No model, network, corpus
mutation or production API call. This does not measure retrieval, writer,
checker, end-to-end latency or live answer quality, and is not a before/after
speedup claim. No new paid calls or production restart.

## Verification

Isolated PostgreSQL fixture (55439), network barrier active: 3229 passed,
0 failed, 0 skipped, 72.25 seconds. JUnit:
`.local/source-selection-20261029.xml`. Browser extension tests were explicitly
outside this backend run; no new browser or paid model comparison is claimed.
An additional source-view invalidation regression was added after collection;
it passed in the separate 45-test focused rerun, not in the 3229 count.
The disposable fixture was stopped after the run; production was untouched.
