"""语料分层工具单测（纯函数，不触 DB）。

分层是闭集：非法层必须显式报错并回报可选值，而不是静默忽略
（静默忽略会让模型以为"限定了范围"，实际全库在查）。
"""
from app.tools import LAYERS, _hit_date, _normalize_layers


def test_all_layers_declared():
    assert set(LAYERS) == {"blog", "basics", "daily"}
    assert "开源日报" in LAYERS["daily"]


def test_none_means_all_layers():
    assert _normalize_layers(None) == (None, None)
    assert _normalize_layers("") == (None, None)
    assert _normalize_layers([]) == (None, None)


def test_single_and_multi_layers():
    assert _normalize_layers("daily") == (["daily"], None)
    assert _normalize_layers(["basics", "daily"]) == (["basics", "daily"], None)


def test_comma_string_accepted():
    assert _normalize_layers("blog, daily") == (["blog", "daily"], None)
    assert _normalize_layers("blog，daily") == (["blog", "daily"], None)


def test_unknown_layer_rejected_with_hint():
    layers, err = _normalize_layers(["daily", "reference"])
    assert layers is None
    assert err is not None and "reference" in err and "daily" in err


def test_daily_date_parse():
    assert _hit_date("daily-20261029") == "2026-10-29"
    assert _hit_date("daily-2026102") is None
    assert _hit_date("blog-07") is None
