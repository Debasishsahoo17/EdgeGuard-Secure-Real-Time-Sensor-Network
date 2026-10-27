from scripts.latency_report import percentile, summarize


def test_nearest_rank_percentiles():
    assert percentile([], .95) == 0
    assert percentile([1, 2, 3, 4, 100], .95) == 100
    assert percentile([4, 2, 5, 8], .50) == 4


def test_aggregated_report_deltas():
    rows = [{"latency_ms":d} for d in [5, 10, 20, 25]]
    first = {"retries":10,"dropped":3,"failed":0,"duplicates":8,"nodes_online":3}
    last = {"retries":15,"dropped":6,"failed":1,"duplicates":9,"nodes_online":2}
    info = summarize(rows,[first,last])
    assert info["latency_avg_ms"] == 15
    assert info["latency_p95_ms"] == 25
    assert info["retries_during_poll"] == 5
    assert info["dropped_during_poll"] == 3
    assert info["active_nodes_at_end"] == 2
