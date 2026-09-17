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
