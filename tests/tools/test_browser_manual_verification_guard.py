import json


def test_bot_detection_result_warns_not_to_use_unrelated_ozon_link(monkeypatch):
    import tools.browser_tool as browser_tool

    monkeypatch.setattr(browser_tool, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(browser_tool, "_is_local_backend", lambda: True)
    monkeypatch.setattr(browser_tool, "_get_session_info", lambda task_id: {
        "session_name": "h_test",
        "features": {"local": True},
    })
    monkeypatch.setattr(browser_tool, "_maybe_start_recording", lambda task_id: None)
    monkeypatch.setattr(browser_tool, "_get_command_timeout", lambda: 30)

    def fake_run(task_id, command, args=None, timeout=None):
        if command == "open":
            return {
                "success": True,
                "data": {
                    "title": "Are you not a robot?",
                    "url": "https://yandex.ru/showcaptcha",
                },
            }
        if command == "snapshot":
            return {"success": True, "data": {"snapshot": "captcha page", "refs": {}}}
        raise AssertionError(command)

    monkeypatch.setattr(browser_tool, "_run_browser_command", fake_run)

    result = json.loads(browser_tool.browser_navigate("https://yandex.ru/search/?text=news", task_id="captcha-test"))

    assert result["success"] is True
    assert "bot_detection_warning" in result
    assert result["manual_verification"]["available"] is False
    assert result["manual_verification"]["same_session_required"] is True
    assert "Ozon" in result["manual_verification"]["reason"]
