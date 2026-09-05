"""config: local restaurant file handling and env parsing."""
import json

import pytest

import config


def test_load_restaurants_reads_the_configured_file(tmp_path, monkeypatch):
    path = tmp_path / "restaurants.json"
    path.write_text(json.dumps([{"name": "Fortune", "line_group_id": "G1"}]), encoding="utf-8")
    monkeypatch.setattr(config, "_RESTAURANTS_FILE", path)

    assert config.load_restaurants()[0]["name"] == "Fortune"


def test_missing_restaurants_file_gives_an_actionable_error(tmp_path, monkeypatch):
    """It is local config now, so a fresh clone will not have it."""
    monkeypatch.setattr(config, "_RESTAURANTS_FILE", tmp_path / "restaurants.json")

    with pytest.raises(RuntimeError, match="restaurants.example.json"):
        config.load_restaurants()


def test_example_file_is_valid_json_and_shipped():
    """The committed example must stay usable as a starting point."""
    assert config._RESTAURANTS_EXAMPLE.exists()
    entries = json.loads(config._RESTAURANTS_EXAMPLE.read_text(encoding="utf-8"))
    assert entries
    for entry in entries:
        assert {"name", "line_group_id", "skip_images"} <= set(entry)


def test_source_group_map_skips_entries_without_a_source(tmp_path, monkeypatch):
    path = tmp_path / "restaurants.json"
    path.write_text(json.dumps([
        {"name": "A", "source_line_group_id": "Csrc", "line_group_id": "Gout"},
        {"name": "B", "line_group_id": "Gout"},
        {"name": "C", "source_line_group_id": "", "line_group_id": "Gout"},
    ]), encoding="utf-8")
    monkeypatch.setattr(config, "_RESTAURANTS_FILE", path)

    mapping = config.build_source_group_map()
    assert list(mapping) == ["Csrc"]
    assert mapping["Csrc"]["name"] == "A"


def test_int_env_rejects_non_numeric(monkeypatch):
    monkeypatch.setenv("SOME_PORT", "not-a-number")
    with pytest.raises(RuntimeError, match="must be an integer"):
        config._int_env("SOME_PORT", 1)


def test_int_env_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("SOME_PORT", raising=False)
    assert config._int_env("SOME_PORT", 5000) == 5000
