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


def test_failed_nudge_is_not_flagged(tmp_path):
    m = _model(tmp_path, '{"w": 30.0, "t": 1.0}',
               "    if P['t'] != 1.0:\n        raise ValueError('too thick')\n"
               "    return B.Box(P['w'], 20, 5)\n")
    notes = []
    flags = sense(m, dict(m.PARAMS), notes=notes)
    assert all(f["params"] != ["t"] for f in flags)
    assert any("t:" in n for n in notes)


def test_through_hole_is_one_flag(tmp_path):
    m = _model(tmp_path, '{"w": 40.0}',
               "    part = B.Box(P['w'], 20, 5)\n"
               "    return part - B.Pos(10, 0, 0) * B.Cylinder(2, 10)\n")
    hard = [f for f in sense(m, dict(m.PARAMS)) if f["kind"] == "hard_coded"]
    assert len(hard) == 1 and hard[0]["detail"].endswith("hole at (10,0)")


def test_centred_bore_is_anchored(tmp_path):
    m = _model(tmp_path, '{"w": 40.0}',
               "    return B.Box(P['w'], 20, 5) - B.Cylinder(2, 10)\n")
    assert sense(m, dict(m.PARAMS)) == []


def test_downward_nudge_and_non_numeric(tmp_path):
    m = _model(tmp_path, '{"w": 30.0, "cap": 30.0, "name": "x"}',
               "    return B.Box(min(P['w'], P['cap']), 20, 5)\n")
    kinds = _kinds(m)
    assert ("no_effect", ["w"]) not in kinds and ("no_effect", ["cap"]) not in kinds


def test_checkpoint_senses_only_changed_parts(plain_dir, monkeypatch):
    import sense as sense_mod
    from cadproj import open_project
    from cadvc import checkpoint
    p = open_project(plain_dir)
    p.parts.mkdir(parents=True, exist_ok=True)
    body = "\ndef build(P):\n    return B.Box(P['w'], 20, 5)\n"
    for n in ("a", "b"):
        (p.parts / f"{n}.py").write_text(HEAD % '{"w": 30.0}' + body, encoding="utf-8")
    checkpoint(p, "one")
    seen = []
    real = sense_mod.sense
    monkeypatch.setattr(sense_mod, "sense",
                        lambda model, P, *a, **k: (seen.append(Path(model.__file__).stem),
                                                   real(model, P, *a, **k))[1])
    (p.parts / "a.params.json").write_text('{"w": 31}', encoding="utf-8")
    checkpoint(p, "two")
    assert seen == ["a"]
