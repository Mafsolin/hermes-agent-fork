from datetime import datetime
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from agent.apistore_limits import (
    API_CHECK_USAGE_URL,
    INVALID_KEY_MESSAGE,
    UNAVAILABLE_MESSAGE,
    fetch_apistore_limits,
    fetch_limits,
    format_limits,
    strip_ansi,
)


SAMPLE_USAGE = {
    "maskedKey": "sk-...abcd",
    "dailyRequests": 292,
    "totalRequests": 1200,
    "dailyTokensUsed": 7_823_900,
    "dailyTokenLimit": 50_000_000,
    "totalTokensUsed": 123_456_789,
    "creditsUsed": 42,
    "creditsLimit": 100,
    "resetsAt": "2026-05-12T09:00:00.000Z",
    "createdAt": "2026-05-01T10:20:30.000Z",
    "expiresAt": "2026-06-06T00:00:00.000Z",
    "daysLeft": 25,
}


def test_strip_ansi_removes_escape_sequences():
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_format_limits_formats_top_level_usage_for_telegram():
    now = datetime(2026, 5, 12, 11, 14, 58, tzinfo=ZoneInfo("Europe/Moscow"))

    result = format_limits(SAMPLE_USAGE, now=now)

    assert result == (
        "API ключ: sk-...abcd\n"
        "Токены: 7 823 900 / 50 000 000 (16%)\n"
        "Запросы: 292\n"
        "Кредиты: 42 / 100\n"
        "Сброс: 00:45:02 до 12:00 МСК\n"
        "Истекает: 06 июн. 2026 г.\n"
        "Статус: Активен"
    )


def test_format_limits_accepts_data_wrapper():
    assert "Токены: 7 823 900 / 50 000 000 (16%)" in format_limits({"data": SAMPLE_USAGE})


def test_format_limits_accepts_usage_wrapper():
    assert "Запросы: 292" in format_limits({"usage": SAMPLE_USAGE})


def test_format_limits_missing_is_active_is_active_after_success():
    assert "Статус: Активен" in format_limits(SAMPLE_USAGE)


def test_format_limits_explicit_is_active_false_is_inactive():
    usage = {**SAMPLE_USAGE, "isActive": False}

    assert "Статус: Неактивен" in format_limits(usage)


def test_format_limits_limit_reached_status():
    usage = {**SAMPLE_USAGE, "disabledReason": "daily_limit_exceeded"}

    assert "Статус: Лимит достигнут" in format_limits(usage)


def test_fetch_limits_posts_bearer_token_and_empty_json_body(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data":{"dailyRequests":1}}'

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["data"] = request.data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("agent.apistore_limits.urlopen", fake_urlopen)

    assert fetch_limits("abc-token", timeout=12) == {"data": {"dailyRequests": 1}}
    assert captured["url"] == API_CHECK_USAGE_URL
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "Bearer abc-token"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["data"] == b"{}"
    assert captured["timeout"] == 12


def test_fetch_apistore_limits_returns_invalid_key_message_on_401(monkeypatch):
    def fake_fetch(token, timeout=0):
        raise HTTPError(
            url=API_CHECK_USAGE_URL,
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("agent.apistore_limits._configured_api_keys", lambda: ["bad-key"])
    monkeypatch.setattr("agent.apistore_limits.fetch_limits", fake_fetch)

    assert fetch_apistore_limits() == INVALID_KEY_MESSAGE


def test_fetch_apistore_limits_returns_unavailable_message_on_network_error(monkeypatch):
    def fake_fetch(token, timeout=0):
        raise URLError("network down")

    monkeypatch.setattr("agent.apistore_limits._configured_api_keys", lambda: ["key"])
    monkeypatch.setattr("agent.apistore_limits.fetch_limits", fake_fetch)

    assert fetch_apistore_limits() == UNAVAILABLE_MESSAGE


def test_fetch_apistore_limits_tries_fallback_keys(monkeypatch):
    attempts = []

    def fake_fetch(token, timeout=0):
        attempts.append(token)
        if token == "bad-key":
            raise HTTPError(
                url=API_CHECK_USAGE_URL,
                code=401,
                msg="Unauthorized",
                hdrs=None,
                fp=None,
            )
        return SAMPLE_USAGE

    monkeypatch.setattr("agent.apistore_limits._configured_api_keys", lambda: ["bad-key", "good-key"])
    monkeypatch.setattr("agent.apistore_limits.fetch_limits", fake_fetch)

    result = fetch_apistore_limits(now=datetime(2026, 5, 12, 11, 14, 58, tzinfo=ZoneInfo("Europe/Moscow")))

    assert attempts == ["bad-key", "good-key"]
    assert "Токены: 7 823 900 / 50 000 000 (16%)" in result
