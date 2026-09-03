from hermes_cli.commands import GATEWAY_KNOWN_COMMANDS, COMMANDS, resolve_command


def test_limits_command_is_registered_for_cli_and_gateway():
    cmd = resolve_command("limits")

    assert cmd is not None
    assert cmd.name == "limits"
    assert "/limits" in COMMANDS
    assert "limits" in GATEWAY_KNOWN_COMMANDS
