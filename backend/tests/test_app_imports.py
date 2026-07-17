import importlib


def test_app_imports():
    app = importlib.import_module("app")
    assert hasattr(app, "handle_message")
