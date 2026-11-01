import httpx
import pytest

from scripts.benchmark_embedding_latency import embed, summary


def test_latency_summary_reports_nearest_rank_p95():
    assert summary([5, 1, 3, 2, 4]) == {"count": 5, "median_ms": 3, "p95_ms": 5, "max_ms": 5}


def test_embedding_benchmark_validates_shape_and_separates_server_loading():
    def reply(request):
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[.5, .5]], "total_duration": 9_000_000,
                                        "load_duration": 3_000_000, "prompt_eval_count": 4})

    with httpx.Client(base_url="http://synthetic.local", transport=httpx.MockTransport(reply)) as client:
        row, vector = embed(client, "synthetic-model", 2, "Synthetic query")
    assert vector == [.5, .5]
    assert row["server_total_ms"] == 9
    assert row["server_load_ms"] == 3
    assert row["prompt_tokens"] == 4
    assert row["client_ms"] >= 0


@pytest.mark.parametrize("vectors", [[], [[1]], [[0, 0]], [[1, 2], [3, 4]]])
def test_invalid_vectors_cannot_count_as_a_successful_latency_sample(vectors):
    with httpx.Client(base_url="http://synthetic.local", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"embeddings": vectors})
    )) as client, pytest.raises(ValueError):
        embed(client, "synthetic-model", 2, "Synthetic query")
