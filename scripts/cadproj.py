"""Per-project cad/ folder: layout, settings, discovery."""
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SETTINGS = {"auto_checkpoint": False}
CAD_GITIGNORE = "exports/\n__pycache__/\n"


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
        gi = cad / ".gitignore"
        if not gi.exists():
            gi.write_text(CAD_GITIGNORE)
    return p


def load_settings(p):
    return json.loads(p.settings_path.read_text())


def save_settings(p, s):
    p.settings_path.write_text(json.dumps(s, indent=2) + "\n")
