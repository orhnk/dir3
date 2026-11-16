"""--recompile: drop disk caches for a fully fresh run."""
import json

from dir3 import cli

PLAN = """\
from datetime import time, timedelta
from dir3 import day, task, week

location = (40.7992, 29.4305, "Europe/Istanbul")


@day
def sample(ctx):
    return [task("X", start=time(9, 0), duration=timedelta(minutes=30))]


plan = week(mon=sample, tue=sample, wed=sample, thu=sample,
            fri=sample, sat=sample, sun=sample)
"""


def _seed_cache(cache_dir) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "prayer_times.json").write_text(json.dumps({"stale": True}), encoding="utf-8")
    (cache_dir / "geolocation.json").write_text(json.dumps({"stale": True}), encoding="utf-8")


def test_recompile_clears_caches(tmp_path, monkeypatch, capsys):
    planfile = tmp_path / "plan.py"
    planfile.write_text(PLAN, encoding="utf-8")
    cache_dir = tmp_path / "cache"
    _seed_cache(cache_dir)
    monkeypatch.setattr("dir3.config.DEFAULT_CACHE_DIR", cache_dir)

    assert cli.main([str(planfile), "--offline", "--until", "1", "--compile", "--recompile"]) == 0
    assert not (cache_dir / "prayer_times.json").exists() or (
        json.loads((cache_dir / "prayer_times.json").read_text(encoding="utf-8")).get("stale")
        is not True
    )
    assert not (cache_dir / "geolocation.json").exists()
    err = capsys.readouterr().err
    assert "frisch" in err


def test_without_recompile_keeps_caches(tmp_path, monkeypatch, capsys):
    planfile = tmp_path / "plan.py"
    planfile.write_text(PLAN, encoding="utf-8")
    cache_dir = tmp_path / "cache"
    _seed_cache(cache_dir)
    monkeypatch.setattr("dir3.config.DEFAULT_CACHE_DIR", cache_dir)

    assert cli.main([str(planfile), "--offline", "--until", "1", "--compile"]) == 0
    assert (cache_dir / "geolocation.json").exists()
    assert "frisch" not in capsys.readouterr().err


def test_recompile_without_cache_still_compiles(tmp_path, monkeypatch, capsys):
    planfile = tmp_path / "plan.py"
    planfile.write_text(PLAN, encoding="utf-8")
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("dir3.config.DEFAULT_CACHE_DIR", cache_dir)

    assert cli.main([str(planfile), "--offline", "--until", "1", "--compile", "--recompile"]) == 0
    assert "Kein Cache" in capsys.readouterr().err
