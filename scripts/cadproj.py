"""Per-project cad/ folder: layout, settings, discovery."""
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SETTINGS = {"auto_checkpoint": False}
CAD_GITIGNORE_LINES = ("exports/", "__pycache__/", ".cad-bench.json")


class ProjectError(Exception):
    pass


@dataclass
class Project:
    root: Path
    cad: Path
    parts: Path
    assemblies: Path
    exports: Path
    settings_path: Path
    skill_scripts: Path


def open_project(working_dir, create=True):
    root = Path(working_dir).resolve()
    cad = root / "cad"
    if not cad.is_dir() and not create:
        raise ProjectError(f"no cad/ folder in {root}")
    p = Project(
        root=root,
        cad=cad,
        parts=cad / "parts",
        assemblies=cad / "assemblies",
        exports=cad / "exports",
        settings_path=cad / ".cad-bench.json",
        skill_scripts=Path(__file__).resolve().parent,
    )
    if create:
        for d in (p.parts, p.assemblies, p.exports):
            d.mkdir(parents=True, exist_ok=True)
        if not p.settings_path.exists():
            save_settings(p, dict(DEFAULT_SETTINGS))
        _ensure_gitignore(cad / ".gitignore")
    return p


def _ensure_gitignore(gi):
    """Add any missing standard lines to cad/.gitignore, keeping the user's own lines."""
    text = gi.read_text() if gi.exists() else ""
    have = {ln.strip() for ln in text.splitlines()}
    missing = [ln for ln in CAD_GITIGNORE_LINES if ln not in have]
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        gi.write_text(text + "".join(ln + "\n" for ln in missing))


def load_settings(p):
    return json.loads(p.settings_path.read_text())


def save_settings(p, s):
    p.settings_path.write_text(json.dumps(s, indent=2) + "\n")
