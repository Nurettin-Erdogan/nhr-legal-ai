# Assistant optimization — 2026-10-24

## Scope and safety

Existing uncommitted changes were preserved. No commit, database migration,
embedding worker restart, cloud billing change, or corpus eligibility change was
performed. Only the JurisAI API was restarted to load the configuration/code.
Verified-source, citation, semantic grounding, and private-document cloud routing
checks remain enabled.

## Changes

- Cloud answers no longer pause bulk embedding for their entire duration. A
  local-generation fallback pauses embedding only while it uses local resources;
  nested fallback scopes preserve a pause that another operator already owns.
- Legislation bge-m3 retrieval can run when the shared query embedding fails.
  Failed embedding attempts now contribute to timing diagnostics.
- Cloud synthesis selects sentence identifiers rather than repeating long source
  quotations. The server resolves those identifiers against the original source,
  then applies the existing factual and independent semantic checks.
- Default-profile evidence selection uses the auxiliary model settings; the deep
  research profile is unchanged.
- Conditional payment language is recognized without accepting unconditional or
  reversed-payment claims. General unpaid-rent questions use the existing verified
  TBK 315 route; product-lease and enforcement-specific questions are excluded from
  that shortcut.
- Configuration tests are isolated from real environment credentials. A key
  exposed by an earlier failing test was disabled with the user's approval and
  replaced only in `.env`. The replacement has a USD 4.90 total limit to leave room
  for earlier usage under the original USD 5 budget. Auto Top-Up remains disabled.

## Verification

Full offline suite: **2056 passed, 433 skipped, 1 warning**. Database integration
tests were not enabled against the production database. `git diff --check` passed.

Live, uncached `POST /api/ai/answer` after the final API restart:

| Question | HTTP | Seconds | Provider / model | Grounded | Citation |
| --- | --- | ---: | --- | --- | --- |
| Kiracı kirayı ödemezse ev sahibi ne yapabilir? | 200 | 12.29 | openrouter / deepseek/deepseek-v4-flash | true | 6098 / 315 |
| Haksız fiilden doğan tazminat taleplerinde zamanaşımı süresi nedir? | 200 | 36.61 | openrouter / deepseek/deepseek-v4-flash | true | 6098 / 72 |

The earlier rent sample took 100.65 seconds. These are individual observations,
not a performance guarantee: the broader limitation-period search remains slower
and marked its candidate retrieval as partial. The same question's earlier sample
took 20.36 seconds, so there is no universal speedup claim.

One intermediate standalone run was invalidated by a database administrator
shutdown signal. The database was not restarted by this work. Final HTTP tests
completed with no cloud fallback or embedding error in the restarted API log.
Uvicorn was listening on `127.0.0.1:8766`; no port-conflict error was present.

Remaining work: investigate broad-query retrieval under concurrent embedding load
and measure a larger quality/latency set without weakening source verification.
