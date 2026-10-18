from pathlib import Path

from partmodel import effective_params, load_model
from sense import sense, summarize

REPO = Path(__file__).resolve().parent.parent

HEAD = '''
import brep as B
PARAMS = %s
def derive(P):
    return dict(P)
'''


def _model(tmp_path, params, body):
    f = tmp_path / "m.py"
    f.write_text(HEAD % params + "\ndef build(P):\n" + body, encoding="utf-8")
    return load_model(f)


def _kinds(model):
    return [(f["kind"], f["params"]) for f in sense(model, dict(model.PARAMS))]


def test_flags_redundant(tmp_path):
    m = _model(tmp_path, '{"a": 20.0, "b": 10.0}',
               "    return B.Box(P['a'] + P['b'], 20, 5)\n")
    assert ("redundant", ["a", "b"]) in _kinds(m)


def test_flags_no_effect(tmp_path):
    m = _model(tmp_path, '{"w": 30.0, "unused": 5.0}',
               "    return B.Box(P['w'], 20, 5)\n")
    assert ("no_effect", ["unused"]) in _kinds(m)


def test_flags_hard_coded_hole(tmp_path):
    m = _model(tmp_path, '{"w": 40.0}',
               "    part = B.Box(P['w'], 20, 5)\n"
               "    return part - B.Pos(10, 0, 0) * B.Cylinder(2, 10)\n")
    flags = sense(m, dict(m.PARAMS))
    hard = [f for f in flags if f["kind"] == "hard_coded"]
    assert hard and "Ø4.0 hole at (10,0)" in hard[0]["detail"]
    assert "hard-coded" in summarize("m", flags)


def test_clean_model_has_no_flags():
    m = load_model(REPO / "models" / "boss_plate.py")
    assert sense(m, effective_params(m)) == []
    assert summarize("boss_plate", []) == "sense boss_plate: clean"


def test_checkpoint_appends_flags_and_survives_sense_failure(plain_dir, monkeypatch):
    import sense as sense_mod
    from cadproj import open_project
    from cadvc import checkpoint
    p = open_project(plain_dir)
    p.parts.mkdir(parents=True, exist_ok=True)
    (p.parts / "m.py").write_text(HEAD % '{"w": 30.0, "unused": 5.0}' +
                                  "\ndef build(P):\n    return B.Box(P['w'], 20, 5)\n",
                                  encoding="utf-8")
    assert checkpoint(p, "one").endswith(" · sense: 1 flag")

    def boom(*a, **k):
        raise RuntimeError("kernel exploded")
    monkeypatch.setattr(sense_mod, "sense", boom)
    (p.parts / "extra.txt").write_text("x", encoding="utf-8")
    line = checkpoint(p, "two")
    assert line.startswith("checkpoint two") and "sense" not in line
