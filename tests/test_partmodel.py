import json
import subprocess
from pathlib import Path

from cadproj import open_project
from partmodel import build_part, effective_params, load_model

REPO = Path(__file__).resolve().parent.parent
PY = r"C:\Users\gritp\cad-bench-venv\Scripts\python"


def _scaffold(plain_dir):
    r = subprocess.run(
        [PY, str(REPO / "scripts" / "new_part.py"), "--project", str(plain_dir),
         "--name", "spacer", "--params", "w=40,t=3"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return open_project(plain_dir)


def test_scaffold_into_project(plain_dir):
    p = _scaffold(plain_dir)
    model = p.parts / "spacer.py"
    assert model.is_file() and (p.parts / "spacer.recipe.js").is_file()
    assert 'file:"cad/parts/spacer.py"' in (p.parts / "spacer.recipe.js").read_text()
    r = subprocess.run([PY, str(model)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (p.exports / "spacer.stl").is_file()


def test_load_model_and_params_override(plain_dir):
    p = _scaffold(plain_dir)
    model = load_model(p.parts / "spacer.py")
    assert effective_params(model, None) == {"w": 40.0, "t": 3.0}
    pj = p.parts / "spacer.params.json"
    pj.write_text(json.dumps({"w": 52.4, "bogus": 1}))
    eff = effective_params(model, pj)
    assert eff == {"w": 52.4, "t": 3.0}
    assert build_part(model, eff) is not None


def test_load_model_reimports_on_mtime_change(plain_dir):
    import os
    p = _scaffold(plain_dir)
    f = p.parts / "spacer.py"
    m1 = load_model(f)
    assert load_model(f) is m1
    f.write_text(f.read_text() + "\nMARK = 1\n")
    st = f.stat()
    os.utime(f, (st.st_atime, st.st_mtime + 5))
    assert getattr(load_model(f), "MARK", None) == 1


def test_examples_still_work():
    r = subprocess.run([PY, str(REPO / "models" / "boss_plate.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
