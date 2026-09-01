"""Helpers for reading provider usage limits over HTTP."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is available in Hermes runtime
    yaml = None

try:
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover - standalone script fallback
    get_hermes_home = None

API_CHECK_USAGE_URL = "https://apistore.space/api/keys/check-usage"
NEUROGATE_ME_URL = "https://api.neurogate.space/v1/me"
INVALID_KEY_MESSAGE = "Ключ не найден или недействителен."
UNAVAILABLE_MESSAGE = "Не удалось обновить данные."
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MONTHS_RU_SHORT = {
    1: "янв.",
    2: "февр.",
    3: "мар.",
    4: "апр.",
    5: "мая",
    6: "июн.",
    7: "июл.",
    8: "авг.",
    9: "сент.",
    10: "окт.",
    11: "нояб.",
    12: "дек.",
}


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text or "")


def _format_int(value: int | float | str | None) -> str:
    if value is None:
        return "Без лимита"
    try:
        return f"{int(float(value)):,}".replace(",", " ")
    except Exception:
        return "0"


def _to_number(value: int | float | str | None) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _local_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(MOSCOW_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=MOSCOW_TZ)
    return current.astimezone(MOSCOW_TZ)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_date(value: str | None) -> str:
    target = _parse_dt(value)
    if target is None:
        return "никогда"
    local = target.astimezone(MOSCOW_TZ)
    month = MONTHS_RU_SHORT.get(local.month, str(local.month))
    return f"{local.day:02d} {month} {local.year} г."


def _format_datetime(value: str | None) -> str:
    target = _parse_dt(value)
    if target is None:
        return "неизвестно"
    local = target.astimezone(MOSCOW_TZ)
    month = MONTHS_RU_SHORT.get(local.month, str(local.month))
    return f"{local.day:02d} {month} {local.year} г., {local:%H:%M}"


def _format_countdown(value: str | None, now: datetime | None = None) -> str:
    target = _parse_dt(value)
    if target is None:
        return "неизвестно"
    now_local = _local_now(now)
    target_local = target.astimezone(MOSCOW_TZ)
    seconds = max(0, int((target_local - now_local).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d} до {target_local:%H:%M} МСК"


def _extract_usage(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("data", "usage"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested
    return payload


def _status_text(usage: dict) -> str:
    if usage.get("isExpired") is True:
        return "Истёк"
    if usage.get("disabledReason") == "daily_limit_exceeded":
        return "Лимит достигнут"
    if usage.get("isActive") is False:
        return "Неактивен"
    return "Активен"


def format_limits(data: object, now: datetime | None = None) -> str:
    """Format apistore.space check-usage JSON for Telegram/CLI output."""
    usage = _extract_usage(data)
    if not usage:
        return UNAVAILABLE_MESSAGE

    daily_used = max(0, _to_number(usage.get("dailyTokensUsed")))
    daily_limit = max(0, _to_number(usage.get("dailyTokenLimit")))
    percent = round(daily_used / daily_limit * 100) if daily_limit else 0

    lines: list[str] = []
    masked_key = str(usage.get("maskedKey") or "").strip()
    if masked_key:
        lines.append(f"API ключ: {masked_key}")

    limit_text = _format_int(daily_limit) if daily_limit else "Без лимита"
    percent_suffix = f" ({percent}%)" if daily_limit else ""
    lines.append(f"Токены: {_format_int(daily_used)} / {limit_text}{percent_suffix}")
    lines.append(f"Запросы: {_format_int(usage.get('dailyRequests') or usage.get('totalRequests') or 0)}")

    if usage.get("creditsUsed") is not None or usage.get("creditsLimit") is not None:
        credits_used = _format_int(usage.get("creditsUsed") or 0)
        credits_limit_raw = usage.get("creditsLimit")
        if credits_limit_raw:
            lines.append(f"Кредиты: {credits_used} / {_format_int(credits_limit_raw)}")
        else:
            lines.append(f"Кредиты: {credits_used}")

    resets_at = usage.get("resetsAt")
    if resets_at:
        lines.append(f"Сброс: {_format_countdown(str(resets_at), now=now)}")

    expires_at = usage.get("expiresAt")
    if expires_at:
        lines.append(f"Истекает: {_format_date(str(expires_at))}")
    else:
        lines.append("Истекает: никогда")

    lines.append(f"Статус: {_status_text(usage)}")
    return "\n".join(lines)


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict | None = None,
    timeout: float = 25.0,
) -> object:
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=data, method=method, headers=req_headers)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def fetch_limits(api_key: str, timeout: float = 25.0) -> object:
    return _request_json(
        API_CHECK_USAGE_URL,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}"},
        body={},
        timeout=timeout,
    )


def fetch_neurogate_limits(api_key: str, timeout: float = 25.0) -> object:
    return _request_json(
        NEUROGATE_ME_URL,
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        timeout=timeout,
    )


def _limit_text(limit: object) -> str:
    if limit is None or limit == "":
        return "Без лимита"
    return _format_int(limit)


def _remaining_text(limit: object, used: object) -> str:
    if limit is None or limit == "":
        return "Без лимита"
    return _format_int(max(0, _to_number(limit) - _to_number(used)))


def _format_neurogate_window(row: dict, label: str, suffix: str) -> list[str]:
    credits = row.get(f"credits{suffix}") or 0
    limit = row.get(f"creditLimit{suffix}")
    lines = [
        f"{label}:",
        f"Сброс: {_format_datetime(row.get(f'window{suffix}EndsAt'))}",
        f"Списано: {_format_int(credits)} / {_limit_text(limit)}",
        f"Осталось: {_remaining_text(limit, credits)}",
    ]
    tokens = row.get(f"tokens{suffix}")
    cached = row.get(f"cachedTokens{suffix}")
    if tokens is not None:
        lines.append(f"Токены всего: {_format_int(tokens)}")
    if cached is not None:
        lines.append(f"Кэш: {_format_int(cached)}")
    return lines


def format_neurogate_limits(data: object) -> str:
    if not isinstance(data, dict):
        return UNAVAILABLE_MESSAGE

    usage = data.get("usage")
    rows = usage.get("rows") if isinstance(usage, dict) else None
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    if not row:
        return UNAVAILABLE_MESSAGE

    lines: list[str] = ["NeuroGate: списано без кэша"]
    email = data.get("email") or data.get("subject")
    plan = data.get("current_plan_code") or row.get("sourcePlanCode")
    if email:
        lines.append(f"Email: {email}")
    if plan:
        lines.append(f"Тариф: {plan}")
    lines.append("")

    windows = [
        ("5 часов", "5Hours"),
        ("24 часа", "24Hours"),
        ("7 дней", "7Days"),
        ("30 дней", "30Days"),
    ]
    for label, suffix in windows:
        if row.get(f"window{suffix}EndsAt") is None and row.get(f"credits{suffix}") is None:
            continue
        lines.extend(_format_neurogate_window(row, label, suffix))
        lines.append("")

    request_parts = []
    for label, suffix in (("5ч", "5Hours"), ("24ч", "24Hours"), ("7д", "7Days"), ("30д", "30Days")):
        request_parts.append(f"Запросы {label}: {_format_int(row.get(f'requests{suffix}') or 0)}")
    lines.extend(request_parts)
    return "\n".join(lines).strip()


def _config_path() -> Path:
    if get_hermes_home is not None:
        return Path(get_hermes_home()) / "config.yaml"
    return Path.home() / ".hermes" / "config.yaml"


def _append_unique(keys: list[str], value: object) -> None:
    key = str(value or "").strip()
    if key and key not in keys:
        keys.append(key)


def _configured_limit_sources() -> list[dict[str, str]]:
    """Return candidate provider keys with base URLs, active model first."""
    sources: list[dict[str, str]] = []

    def append_source(api_key: object, base_url: object = "", name: object = "") -> None:
        key = str(api_key or "").strip()
        if not key:
            return
        source = {
            "api_key": key,
            "base_url": str(base_url or "").strip(),
            "name": str(name or "").strip(),
        }
        if all(existing["api_key"] != key for existing in sources):
            sources.append(source)

    for env_name in ("APISTORE_API_KEY", "FASTAI_API_KEY"):
        append_source(os.getenv(env_name), name=env_name)

    if yaml is None:
        return sources

    path = _config_path()
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return sources

    model_config = config.get("model") if isinstance(config, dict) else {}
    if isinstance(model_config, dict):
        append_source(
            model_config.get("api_key"),
            model_config.get("base_url"),
            model_config.get("provider"),
        )

    providers = config.get("custom_providers") if isinstance(config, dict) else None
    if isinstance(providers, list):
        scored: list[tuple[int, dict]] = []
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            name = str(provider.get("name") or provider.get("provider") or "").lower()
            base_url = str(provider.get("base_url") or "").lower()
            score = 0
            if "neurogate.space" in base_url:
                score += 40
            if "apistore.space" in base_url:
                score += 30
            if "fastai" in name or "fastai" in base_url:
                score += 20
            if "107.172.62.211" in base_url or "sslip.io" in base_url:
                score += 10
            if score:
                scored.append((score, provider))
        for _score, provider in sorted(scored, key=lambda item: item[0], reverse=True):
            append_source(provider.get("api_key"), provider.get("base_url"), provider.get("name"))

    return sources


def _configured_api_keys() -> list[str]:
    """Return candidate FastAIStore keys, preferring the active model key."""
    keys: list[str] = []
    for source in _configured_limit_sources():
        _append_unique(keys, source.get("api_key"))
    return keys


def fetch_apistore_limits(timeout: float = 25.0, now: datetime | None = None) -> str:
    sources = _configured_limit_sources()
    # Keep the small public seam used by older downstream integrations. When
    # the richer provider scan has no configured entries, explicit API-store
    # keys still form valid fallback sources.
    if not sources:
        sources = [
            {"api_key": api_key, "base_url": API_CHECK_USAGE_URL, "name": "API Store"}
            for api_key in _configured_api_keys()
        ]
    if not sources:
        return UNAVAILABLE_MESSAGE

    saw_invalid_key = False
    for source in sources:
        api_key = source["api_key"]
        base_url = source.get("base_url", "").lower()
        try:
            if "neurogate.space" in base_url:
                payload = fetch_neurogate_limits(api_key, timeout=timeout)
                return format_neurogate_limits(payload)
            payload = fetch_limits(api_key, timeout=timeout)
            return format_limits(payload, now=now)
        except HTTPError as exc:
            if exc.code in (401, 403):
                saw_invalid_key = True
                continue
            return UNAVAILABLE_MESSAGE
        except (URLError, TimeoutError, json.JSONDecodeError, OSError):
            return UNAVAILABLE_MESSAGE

    if saw_invalid_key:
        return INVALID_KEY_MESSAGE
    return UNAVAILABLE_MESSAGE


format_apistore_limits = format_limits
format_codex_limits_from_status = format_limits
fetch_codex_limits = fetch_apistore_limits


if __name__ == "__main__":
    print(fetch_apistore_limits())
