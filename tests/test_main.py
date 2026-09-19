from utm_connector import main


def test_run_uses_uvicorn_application_factory(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(application: str, **kwargs: object) -> None:
        captured["application"] = application
        captured.update(kwargs)

    monkeypatch.setattr(main.uvicorn, "run", fake_run)
    main.run()

    assert captured["application"] == "utm_connector.api:create_app"
    assert captured["factory"] is True


def test_run_can_open_the_operator_console_after_startup(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeTimer:
        def __init__(self, delay: float, function, args=()) -> None:
            captured["delay"] = delay
            captured["function"] = function
            captured["args"] = args
            self.daemon = False

        def start(self) -> None:
            captured["started"] = True

    def fake_run(application: str, **kwargs: object) -> None:
        captured["application"] = application
        captured.update(kwargs)

    monkeypatch.setattr(main.threading, "Timer", FakeTimer)
    monkeypatch.setattr(main.uvicorn, "run", fake_run)
    monkeypatch.setattr(main.sys, "argv", ["utm-connector", "--open-browser"])
    main.run()

    assert captured["function"] is main.webbrowser.open
    assert captured["args"] == ("http://127.0.0.1:8000/",)
    assert captured["started"] is True
    assert captured["application"] == "utm_connector.api:create_app"


def test_run_demo_flag_configures_a_self_contained_vehicle(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(application: str, **kwargs: object) -> None:
        captured["application"] = application
        captured.update(kwargs)

    monkeypatch.delenv("UTM_CONNECTOR_BACKEND", raising=False)
    monkeypatch.delenv("UTM_CONNECTOR_DEMO_MODE", raising=False)
    monkeypatch.delenv("UTM_CONNECTOR_MAVLINK_CONNECTIONS", raising=False)
    monkeypatch.setattr(main.uvicorn, "run", fake_run)
    monkeypatch.setattr(main.sys, "argv", ["utm-connector", "--demo"])

    main.run()

    assert captured["application"] == "utm_connector.api:create_app"
    assert main.ConnectorSettings().backend == "in-memory"
    assert main.ConnectorSettings().demo_mode is True
    assert main.ConnectorSettings().mavlink_connections == []
