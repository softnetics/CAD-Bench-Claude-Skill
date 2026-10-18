"""build_skill_bundle.py: what the one-file install holds, reproducibly."""
import zipfile

import build_skill_bundle as SB


def test_bundle_holds_the_runtime_and_nothing_excluded(tmp_path):
    out = tmp_path / "cad-bench.skill"
    SB.build(out)
    names = zipfile.ZipFile(out).namelist()
    assert all(n.startswith("cad-bench/") for n in names)
    for want in ("SKILL.md", "README.md", "HOWTO.md", "LICENSE", "scripts/assembly.py",
                 "scripts/rules.py", "scripts/mjcf.py", "scripts/asm_export.py",
                 "scripts/asm_render.py", "scripts/cad.py", "scripts/bench_server.py",
                 "assets/live-bench.html", "references/assembly.md",
                 "models/boss_plate.py", "docs/screenshots/01-sliders-drawing.png"):
        assert "cad-bench/" + want in names, want
    for n in names:
        rel = n[len("cad-bench/"):]
        assert not rel.startswith(("tests/", "library/", ".superpowers/", "docs/superpowers/"))
        assert "exports/" not in rel and "__pycache__" not in rel
        assert not any(w in rel for w in ("balance", "bb_", "wheel" + "-hub", "hinge_box", "fixtures"))
        assert not rel.startswith("models/rules/")
        assert not rel.endswith(".stl") and not rel.startswith("models/_")


def test_bundle_is_reproducible(tmp_path):
    a, b = tmp_path / "a.skill", tmp_path / "b.skill"
    SB.build(a)
    SB.build(b)
    assert a.read_bytes() == b.read_bytes()
