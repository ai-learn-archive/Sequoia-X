"""飞书通知属性测试。"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

import sequoia_x.notify.feishu as feishu_module
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from sequoia_x.core.config import Settings
from sequoia_x.notify.feishu import FeishuNotifier


def make_settings(webhook_url: str = "https://example.com/default") -> Settings:
    return Settings(
        db_path="data/test.db",
        start_date="2024-01-01",
        feishu_webhook_url=webhook_url,
    )


@pytest.fixture(autouse=True)
def _mock_feishu_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """避免测试调用 AkShare / baostock；飞书 HTTP mock 需返回 code=0。"""
    import sequoia_x.notify.shenwan_industry as sw

    monkeypatch.setattr(sw, "fetch_symbol_to_industry_code", lambda: {})
    monkeypatch.setattr(
        feishu_module.FeishuNotifier,
        "_get_stock_names",
        staticmethod(lambda symbols: {s: s for s in symbols}),
    )


def _feishu_ok_response() -> MagicMock:
    m = MagicMock(status_code=200)
    m.json.return_value = {"code": 0}
    m.text = "{}"
    return m


# Feature: sequoia-x-v2, Property 10: 飞书通知包含所有选股结果
@given(
    symbols=st.lists(
        st.text(min_size=6, max_size=6, alphabet="0123456789"),
        min_size=1, max_size=10, unique=True,
    )
)
@h_settings(max_examples=50)
def test_notification_contains_all_symbols(symbols: list[str]) -> None:
    """属性 10：send() 发出的请求体应包含所有 symbol。"""
    settings = make_settings()
    notifier = FeishuNotifier(settings)

    with patch("requests.post") as mock_post:
        mock_post.return_value = _feishu_ok_response()
        notifier.send(symbols=symbols, strategy_name="TestStrategy")

    call_args = mock_post.call_args
    body = json.loads(call_args.kwargs.get("data") or call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["data"])
    card_text = json.dumps(body)
    for symbol in symbols:
        assert symbol in card_text


# Feature: sequoia-x-v2, Property 11: 飞书通知使用 ConfigManager 中的 Webhook URL
@given(
    webhook_url=st.from_regex(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[a-z0-9\-]{8,36}", fullmatch=True)
)
@h_settings(max_examples=50)
def test_notification_uses_config_url(webhook_url: str) -> None:
    """属性 11：send() 发出的 HTTP 请求目标 URL 应等于 settings.feishu_webhook_url。"""
    settings = make_settings(webhook_url=webhook_url)
    notifier = FeishuNotifier(settings)

    with patch("requests.post") as mock_post:
        mock_post.return_value = _feishu_ok_response()
        notifier.send(symbols=["000001"], strategy_name="Test", webhook_key="default")

    called_url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url")
    assert called_url == webhook_url


# Feature: sequoia-x-v2, Property 12: HTTP 失败时记录 ERROR 日志
@given(status_code=st.integers(min_value=400, max_value=599))
@h_settings(max_examples=50)
def test_http_failure_logs_error(status_code: int) -> None:
    """属性 12：非 200 响应时，send() 应记录 ERROR 级别日志，不抛出异常。"""
    import logging as _logging
    import sequoia_x.notify.feishu as feishu_module

    settings = make_settings()
    notifier = FeishuNotifier(settings)

    # feishu logger 设置了 propagate=False，需直接在其上挂 handler
    feishu_logger = _logging.getLogger(feishu_module.__name__)
    log_records: list[_logging.LogRecord] = []

    class _ListHandler(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            log_records.append(record)

    handler = _ListHandler(_logging.ERROR)
    feishu_logger.addHandler(handler)
    try:
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=status_code, text="error")
            notifier.send(symbols=["000001"], strategy_name="Test")
    finally:
        feishu_logger.removeHandler(handler)

    assert any(r.levelno == _logging.ERROR for r in log_records)


def test_parse_sw_frontmatter_from_obsidian_style_file(tmp_path) -> None:
    """与 obsidian-shenwan 股票笔记 frontmatter 一致时可解析申万三级。"""
    from sequoia_x.notify.shenwan_industry import parse_sw_frontmatter

    md = tmp_path / "ST长投 600119.md"
    md.write_text(
        '---\n'
        '申万一级行业: "交通运输"\n'
        '申万二级行业: "物流"\n'
        '申万三级行业: "跨境物流"\n'
        "---\n# x\n",
        encoding="utf-8",
    )
    assert parse_sw_frontmatter(md) == ("交通运输", "物流", "跨境物流")


def test_nested_pick_list_groups_by_sw_industry() -> None:
    """选股列表按申万层级嵌套；行业代码未命中时归入未分类。"""
    from sequoia_x.notify.shenwan_industry import build_nested_pick_markdown

    l3 = {"110101": ("农林牧渔", "种植业", "种子")}
    l2: dict[str, tuple[str, str]] = {}
    text = build_nested_pick_markdown(
        ["000001", "000002"],
        {
            "000001": "[A](https://xueqiu.com/S/SZ000001)",
            "000002": "[B](https://xueqiu.com/S/SZ000002)",
        },
        l3,
        l2,
        {"000001": "110101"},
    )
    assert "- 农林牧渔" in text
    assert "  - 种植业" in text
    assert "    - 种子" in text
    assert "[A]" in text
    assert "- 未分类" in text and "[B]" in text
