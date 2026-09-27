from dataclasses import replace

from api.ai.live_verify import verify_third_party_contexts
from ingestion.seed_verify import seed_matches_official
from ingestion.yargitay.portal import CaptchaRequiredError
from tests.factories import court_decision_context


def test_seed_matches_official_ignores_whitespace_and_markup():
    seed = "Kıdem tazminatı doğar."
    official = "  Kıdem   tazminatı\n doğar.  "
    assert seed_matches_official(seed, official)
    assert not seed_matches_official(seed, "Başka bir metin.")


def test_live_verify_promotes_matching_third_party_source(monkeypatch):
    context = replace(court_decision_context(), verification="third_party")
    row = {
        "id": context.source_id,
        "external_id": "yargitay:1224329000",
        "raw_text": context.content,
    }

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            class Result:
                def fetchall(self):
                    return [row]

            return Result()

    monkeypatch.setattr("api.ai.live_verify.database_connection", lambda: Connection())
    promoted = []

    updated = verify_third_party_contexts(
        [context],
        fetcher=lambda kind, document_id: context.content,
        promoter=lambda source_id, kind, document_id, official: promoted.append(
            (source_id, kind, document_id)
        ),
    )

    assert updated[0].verification == "official"
    assert promoted == [(context.source_id, "yargitay", "1224329000")]


def test_live_verify_keeps_badge_when_portal_blocks(monkeypatch):
    context = replace(court_decision_context(), verification="third_party")
    row = {
        "id": context.source_id,
        "external_id": "yargitay:1",
        "raw_text": context.content,
    }

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            class Result:
                def fetchall(self):
                    return [row]

            return Result()

    monkeypatch.setattr("api.ai.live_verify.database_connection", lambda: Connection())

    def blocked(kind, document_id):
        raise CaptchaRequiredError("CAPTCHA")

    updated = verify_third_party_contexts(
        [context],
        fetcher=blocked,
        promoter=lambda *args: (_ for _ in ()).throw(AssertionError("yazılmamalı")),
    )
    assert updated == []
