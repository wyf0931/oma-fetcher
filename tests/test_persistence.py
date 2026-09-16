from app.main import persistence_preference


def test_query_preference_overrides_header_and_default() -> None:
    assert persistence_preference(False, "persist", True) == (False, "query")
    assert persistence_preference(True, None, False) == (True, "query")


def test_prefer_header_overrides_default() -> None:
    assert persistence_preference(None, "respond-async, persist", False) == (True, "prefer")
    assert persistence_preference(None, "handling=lenient", True) == (True, "default")
