"""Load a day definition from a ``path[:attr]`` spec for ``--today``/``--on``.

A spec points at one of the user's day functions/files without touching the
main code-flow (``make_plan``/``plan``/``month``). If the file holds exactly
one day, ``attr`` can be omitted and is picked automatically.
"""
from __future__ import annotations

import hashlib
import importlib.util
import traceback
from pathlib import Path
from typing import Any

from .core import Day, DayFactory

FREE_WORDS = frozenset({"free", "none", "off", "frei", "leer"})


def list_day_candidates(module: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in dir(module):
        if key.startswith("_"):
            continue
        try:
            value = getattr(module, key)
        except Exception:
            continue
        if isinstance(value, (Day, DayFactory)):
            out[key] = value
    return out


def _resolve_path(raw: str, base_dir: Path | None) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate
    cwd_hit = Path.cwd() / candidate
    if cwd_hit.exists():
        return cwd_hit
    if base_dir is not None:
        base_hit = base_dir / candidate
        if base_hit.exists():
            return base_hit
    return candidate


def _split_spec(spec: str) -> tuple[str, str | None]:
    if ":" not in spec:
        return spec, None
    left, _, right = spec.rpartition(":")
    if not left or not right:
        return spec, None
    if len(left) == 1:
        return spec, None
    if "/" in right or "\\" in right:
        return spec, None
    return left, right


def _load_file_module(path: Path):
    if not path.exists():
        raise ValueError(f"Day-Datei existiert nicht: {path}")
    if not path.is_file():
        raise ValueError(f"Day-Pfad ist keine Datei: {path}")
    digest = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:10]
    mod_name = f"dir3_day_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Kann Day-Datei nicht laden: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        if isinstance(exc, SystemExit):
            raise
        traceback.print_exc()
        raise ValueError(f"Fehler in Day-Datei {path}: {exc}") from exc
    return module


def load_day_spec(spec: str, base_dir: Path | None = None) -> Any | None:
    text = spec.strip()
    if not text:
        raise ValueError("Leere Day-Angabe")
    if text.lower() in FREE_WORDS:
        return None
    raw_path, attr = _split_spec(text)
    path = _resolve_path(raw_path, base_dir)
    module = _load_file_module(path)
    if attr is not None:
        if not hasattr(module, attr):
            known = ", ".join(sorted(list_day_candidates(module))) or "keine"
            raise ValueError(f"{path} hat kein Day '{attr}' (verfügbar: {known})")
        value = getattr(module, attr)
        if isinstance(value, (Day, DayFactory)) or callable(value):
            return value
        raise ValueError(f"{path}:{attr} ist kein Day (Typ {type(value).__name__})")
    candidates = list_day_candidates(module)
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    if not candidates:
        raise ValueError(f"{path} enthält kein Day (@day-Funktion fehlt)")
    names = ", ".join(sorted(candidates))
    raise ValueError(f"{path} enthält mehrere Days ({names}) - bitte 'pfad:name' angeben")
