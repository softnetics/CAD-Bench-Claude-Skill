import pytest

from cadproj import ProjectError, load_settings, open_project


def test_creates_layout(plain_dir):
    p = open_project(plain_dir)
    assert p.parts.is_dir() and p.assemblies.is_dir() and p.exports.is_dir()
    assert p.cad.is_dir()
    assert load_settings(p) == {"auto_checkpoint": False}
    assert "exports/" in (p.cad / ".gitignore").read_text()


def test_idempotent_and_non_destructive(plain_dir):
    p = open_project(plain_dir)
    (p.parts / "x.py").write_text("keep")
    open_project(plain_dir)
    assert (p.parts / "x.py").read_text() == "keep"


def test_open_without_create_raises(plain_dir):
    with pytest.raises(ProjectError):
        open_project(plain_dir, create=False)


def test_project_in_path_with_spaces(plain_dir):
    assert " " in plain_dir.name
    p = open_project(plain_dir)
    assert p.root == plain_dir.resolve()
    assert p.settings_path.is_file()


def test_gitignore_excludes_settings_and_upgrades_existing(plain_dir):
    p = open_project(plain_dir)
    assert ".cad-bench.json" in (p.cad / ".gitignore").read_text().splitlines()
    gi = p.cad / ".gitignore"
    gi.write_text("exports/\n__pycache__/\nmine.tmp")  # older project, no trailing newline
    open_project(plain_dir)
    open_project(plain_dir)
    lines = gi.read_text().splitlines()
    assert lines == ["exports/", "__pycache__/", "mine.tmp", ".cad-bench.json"]
