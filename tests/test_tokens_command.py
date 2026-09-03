"""Tests for /tokens as the canonical token usage command."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_tokens_is_canonical_command_and_usage_alias():
    from hermes_cli.commands import COMMANDS, GATEWAY_KNOWN_COMMANDS, resolve_command

    tokens = resolve_command("tokens")
    usage = resolve_command("usage")

    assert tokens is not None
    assert tokens.name == "tokens"
    assert usage is not None
    assert usage.name == "tokens"
    assert "tokens" in GATEWAY_KNOWN_COMMANDS
    assert "usage" in GATEWAY_KNOWN_COMMANDS
    assert "/tokens" in COMMANDS
    assert "/usage" in COMMANDS


def _make_gateway_event(command: str):
    from gateway.config import Platform

    event = MagicMock()
    event.get_command.return_value = command
    event.get_command_args.return_value = ""
    event.message_type = None
    source = MagicMock()
    source.platform = Platform.TELEGRAM
    source.user_id = "123"
    source.user_name = "tester"
    event.source = source
    return event


def test_gateway_tokens_command_uses_usage_report():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock(return_value=None)
    runner._draining = False
    runner.config = {}
    event = _make_gateway_event("tokens")

    with patch.object(runner, "_session_key_for_source", return_value="sk"), \
         patch.object(runner, "_handle_tokens_command", return_value="token report") as mock_tokens:
        result = asyncio.run(runner._handle_message(event))

    assert result == "token report"
    mock_tokens.assert_awaited_once_with(event)


def test_gateway_usage_alias_uses_tokens_report():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock(return_value=None)
    runner._draining = False
    runner.config = {}
    event = _make_gateway_event("usage")

    with patch.object(runner, "_session_key_for_source", return_value="sk"), \
         patch.object(runner, "_handle_tokens_command", return_value="token report") as mock_tokens:
        result = asyncio.run(runner._handle_message(event))

    assert result == "token report"
    mock_tokens.assert_awaited_once_with(event)


def test_cli_tokens_command_uses_usage_report():
    from cli import HermesCLI

    cli_obj = HermesCLI.__new__(HermesCLI)
    cli_obj.console = MagicMock()

    with patch.object(cli_obj, "_show_tokens") as mock_tokens:
        cli_obj.process_command("/tokens")

    mock_tokens.assert_called_once_with()


def test_cli_usage_alias_uses_tokens_report():
    from cli import HermesCLI

    cli_obj = HermesCLI.__new__(HermesCLI)
    cli_obj.console = MagicMock()

    with patch.object(cli_obj, "_show_tokens") as mock_tokens:
        cli_obj.process_command("/usage")

    mock_tokens.assert_called_once_with()
