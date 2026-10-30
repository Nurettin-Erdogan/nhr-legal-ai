"""Her planlayıcı parçasının kendi aramasının zaman aşımı kaydedilir (ağ/DB gerektirmez).

Cevap bu parça aramalarından kurulur. Dış (ham soru) arama eksiksiz bitse bile bir parçanın aramasında kol zaman aşımına
uğradıysa ya da örneklendiyse araştırma eksik olabilir ve kullanıcıya bu söylenmelidir (2026-10-30: "icra takibi" /
"itirazın iptali" parçaları 7,4 sn'de zaman aşımına uğruyor, uyarı ise hiç görünmüyordu).
"""

from contextlib import contextmanager
from types import SimpleNamespace

from api.ai import free_answer, pipeline
from api.ai.verification import VerifiedAnswer
from tests.factories import legislation_context


def test_each_part_search_records_whether_one_of_its_lanes_ran_out_of_time(monkeypatch):
    local = legislation_context(content="Madde 315 - Kiracı borcunu ödemelidir.")

    @contextmanager
    def connection():
        yield object()

    def search(conn, *, question, top_k, diagnostics=None, **kwargs):
        if diagnostics is not None:
            slow = question == "icra takibi"
            diagnostics.update(
                partial=slow,
                branches=[{"name": "lexical", "status": "timeout_then_official" if slow else "ok",
                           "seconds": 7.4 if slow else 0.2}])
        return [local]

    monkeypatch.setattr(pipeline, "database_connection", connection)
    monkeypatch.setattr(pipeline, "get_settings", lambda: SimpleNamespace(
        legislation_embedding_model="", cloud_ai_provider="", official_web_research_enabled=False))
    monkeypatch.setattr(pipeline, "retrieve_contexts", search)
    monkeypatch.setattr(pipeline, "_case_statute_contexts", lambda *a, **kw: [])
    monkeypatch.setattr(free_answer, "plan_question", lambda *a: [("Kira", ("kira",)), ("İcra", ("icra takibi",))])

    def write(provider, **kwargs):
        for sentence in ("kira", "icra takibi"):
            kwargs["retrieve"](sentence)
        return VerifiedAnswer("Kaynaklı cevap.", tuple(kwargs["contexts"]), ())

    monkeypatch.setattr(free_answer, "free_verified_answer", write)
    timings = pipeline.PipelineTimings()

    assert pipeline._free_answer(object(), "Kira ve icra takibi", [local], [], timings, object()) is not None

    searches = {item["query"]: item for item in timings.extra["part_searches"]}
    assert searches["kira"]["partial"] is False and searches["kira"]["limit"] == "none"
    assert searches["icra takibi"]["partial"] is True and searches["icra takibi"]["limit"] == "sampled"
    assert ("lexical", "timeout_then_official", 7.4) in searches["icra takibi"]["branches"]
