# Request-local targeted answer repair — 2026-10-29

The bounded second attempt now asks the writer only for missing/rejected
sentences when a previous verified subset and an identical source view exist.
Retained annotated sentences are combined with the patch before all mechanical
guards and the independent semantic checker run again. Previous prose is not
evidence. A source-view/content/order change invalidates reuse and falls back
to the existing complete revision. No extra call loop or unchecked preview is
introduced. The two-attempt and existing time budgets remain unchanged.

Diagnostics distinguish numeric/polarity gates, evidence binding, explicit
missing-evidence findings, wording/condition findings, and other semantic
rejections. Categories are diagnostic, not proof that a rejection was correct.

Post-check structural removals invalidate the earlier completeness verdict.
Only displayed claims contribute final cited sources and part coverage. Part
coverage remains a conservative source-binding check, not a new semantic proof
that every requested facet is answered. Independent checker coverage still
applies. Partial checked answers remain possible and cannot enter the complete
answer cache; this change does not guarantee complete answers to all questions.

Offline tests cover combined rechecking, retained text, unsafe numeric patches,
and rejection classification. No new paid model calls, production restart,
configuration changes or corpus mutations were performed. Actual latency and
model-quality improvement require a separately authorized live measurement.

Source selection/relevance optimization is not part of this change.
