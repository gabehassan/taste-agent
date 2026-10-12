from tasteserver import db


def test_dated_model_snapshots_are_priced(sent):
    db.set_setting("model_prices", {"m": {"in": 1.0, "out": 2.0}, "m-mini": {"in": 0.1, "out": 0.2}})
    assert db.price_for("m") == {"in": 1.0, "out": 2.0}
    assert db.price_for("m-2026-08-01") == {"in": 1.0, "out": 2.0}
    assert db.price_for("m-mini-2026-08-01") == {"in": 0.1, "out": 0.2}
    assert db.price_for("other") == {}
    assert db.record_usage(None, "llm", "m-2026-08-01", input_tokens=1_000_000, output_tokens=0) == 1.0
