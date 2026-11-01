# Assistant deployment and bounded live acceptance — 2026-10-29

## Status

The API was restarted with user confirmation that no chat, analysis or UYAP
transfer was active. It returned HTTP 200 for health/OpenAPI, exposed the answer
route, and logged the 127.0.0.1:8766 Uvicorn listener without WinError 10048.
No corpus/embedding worker or production database was restarted.

**Live acceptance is not fully passed.** Automated regression success must not
be confused with reliable, complete legal answers across arbitrary questions.
Remaining observed problems include inconsistent semantic-checker rejection,
omitted facets and repeated paraphrases in repaired answers. No claim that all
official sites, all corpus records or all possible questions were tested.

## Changes exercised in this run

- Additional routing to verified procedural provisions: 2576/5, 2004/58, 66,
  67 and 68; these are retrieval hints, not hard-coded legal answers.
- Quantified PDF extraction form `bir sen e` recognized by numeric comparison
  only; original source/display text not rewritten. `senet` is not a year unit.
- Checker reasons remapped from post-filter candidate IDs to original draft
  IDs, preventing wrong repair instructions after a numeric rejection.
- Mechanical failure categories included in repair feedback, alongside
  semantic findings; feedback is not evidence.
- Consistent source-bound inference policy across sentence positions; explicit
  user facts may instantiate retrieved rules, but missing conditions, new
  legal rules, unsupported numbers and fabricated citations remain forbidden.
- Inclusive age boundary protection: `18 ve daha küçük` cannot become
  `18 yaşını doldurmamış`, nor vice versa.
- Both public plan types use strict finite JSON schemas matching their existing
  parsers. This does not impose a new length limit on user-facing prose.

## Live budget / methodology

User cap: **0.05 USD**, existing OpenRouter credit only. Five report ledgers:

| Report suffix | Debited USD | Result |
| --- | ---: | --- |
| `live-20261029` | 0.015492555 | Four low-effort public synthetic answers |
| `live-recheck-20261029` | 0.006054120 | One answer; subsequent case stopped before an unaffordable reserved call |
| `live-admin-20261029` | 0.001575040 | One administrative answer |
| `live-policy-20261029` | 0.010384790 | Two answers; one planner call reached the evaluation's 8192-token cap |
| `live-schema-20261029` | 0.001855675 | Strict plan accepted; subsequent repair stopped before dispatch by the budget reservation |
| **Total** | **0.035362180** | **45 charged calls, eight completed answers** |

Full reports are `.local/final-assistant-<suffix>.json`; no API headers/keys
are recorded. No card/top-up/key-limit changes. The first sandbox connection
failure occurred on the public model catalog before charged dispatch.

Actual production pipeline code and local corpus were used in a separate
evaluation process, not a simplified substitute prompt. Official web ingestion
was process-locally disabled to prevent corpus writes. Requests contained only
synthetic public questions, no saved chats or private user documents. These are
not authenticated browser/HTTP end-to-end latency measurements.

The first pilots used 16384 evaluation output tokens; later budget-constrained
pilots used 8192/4096. Production output settings were not changed. The 8192
planner saturation is a failed performance case, not passed off as normal.
The subsequent strict-schema plan completed in about 3 seconds / 188 output
tokens; this single observation does not establish a latency guarantee.

## Observed answer quality and latency

- Employment answer retained conditions, worker count and application dates:
  37.872 seconds, grounded, source checks passed. Some duplicated prose remained.
- Enforcement improved from a single surviving peripheral statement to
  senetsiz takip, objection, suspension and one-year route: 34.395 seconds.
  The alternative removal route remained incomplete; acceptance failed.
- Administrative answer found both forum and 60-day provision after routing
  repair (23.888 seconds). Later repetition varied and marked partial; the
  checker still rejected some valid-looking contextual formulations. No
  blanket claim of expert-approved legal correctness.
- Leave durations/age handling remained inconsistent. An unsafe birthday
  boundary was identified and given a deterministic regression guard. General
  service-duration coverage still requires work; this case is not accepted.

Automatic citation/ref checks are not expert legal review. Raw diagnostic
`coverage_preserved` can disagree with actual completeness, and is not used
here as an independent pass/fail oracle. Paid testing stopped; the unused
approval is not automatically spent in later turns.

## Automated evidence

The final code runs are reported separately below; interrupted or earlier
failure runs are not counted as passing. Browser tests use their own synthetic
portal, separate Chromium profile and blocked external traffic. No real UYAP
credentials/session were exercised.

SQL V2 schema and RLS checks passed with rollback; V1-to-V2 upgrade assertions
passed in the separate `nhr_upgrade_final_20261029_test` fixture database.
Frontend: 574 passed, 0 failed/skipped; typecheck passed. Production build
passed on the explicit cmd rerun (the earlier PowerShell invocation reported
a native stderr warning as exit 1 and is not counted). Lint: 0 errors,
23 pre-existing warnings, not a warning-free result.

Final backend: **3238 passed, 0 failed, 0 skipped**, 79.56 seconds,
`.local/final-assistant-backend-r7-20261029.xml`. Chromium extension:
**155 passed, 0 failed, 0 skipped**, 27m46s,
`.local/final-assistant-browser-20261029.xml`. Frontend: **574 passed**.
Total: **3967 successful automated behavior tests**; repeated intermediate
runs are not added again. All defined Python test files were covered across
the two final runs; the backend's browser exclusion was compensated by the
separate complete browser run. No failed live quality case was relabelled
as an automated pass. The isolated test container was stopped afterwards.

The API was restarted again after the last production-code change; health
200 and the 8766 listener were confirmed. Final test-file changes after the
full run removed trailing blank lines only.

OpenAI documentation checked for schema support:
https://developers.openai.com/api/docs/guides/structured-outputs . JSON shape
constraints do not establish legal correctness or guarantee answer completeness.
