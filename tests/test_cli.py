import json
import subprocess
import sys
from pathlib import Path

from cadproj import open_project
from cadvc import checkpoint, keep, revert, try_

REPO = Path(__file__).resolve().parent.parent
CAD = REPO / "scripts" / "cad.py"


def cad(project, *args):
    return subprocess.run([sys.executable, str(CAD), *args, "--project", str(project)],
                          capture_output=True, text=True, encoding="utf-8")


def lines(r):
    return [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]


def test_each_command_prints_one_line(git_repo):
    notes = git_repo / "cad" / "parts" / "notes.txt"
    steps = [
        (("init",), None),
        (("checkpoint", "first"), "v1\n"),
        (("try", "taller", "boss"), None),
        (("checkpoint",), "v2\n"),
        (("revert", "too", "tall"), None),
        (("try", "wider"), None),
        (("keep",), "v3\n"),
        (("back",), None),
        (("forward",), None),
        (("auto", "on"), None),
        (("history",), None),
    ]
    for args, write in steps:
        if write is not None:
            notes.write_text(write)
        r = cad(git_repo, *args)
        assert r.returncode == 0, (args, r.stdout, r.stderr)
        assert len(lines(r)) == 1, (args, r.stdout, r.stderr)
        assert r.stderr == "", (args, r.stderr)
    assert notes.read_text() == "v3\n"
    r = cad(git_repo, "history")
    assert r.stdout.startswith("history all: 2 checkpoints, 1 try, latest ")
    r = cad(git_repo, "history", "--json")
    rows = json.loads(r.stdout)
    assert {row["kind"] for row in rows} >= {"checkpoint", "kept", "abandoned"}


def test_error_is_one_line_and_nonzero(git_repo):
    assert cad(git_repo, "init").returncode == 0
    (git_repo / "cad" / "parts" / "notes.txt").write_text("x\n")
    assert cad(git_repo, "checkpoint").returncode == 0
    subprocess.run(["git", "checkout", "-q", "--detach"], cwd=git_repo, check=True)
    (git_repo / "cad" / "parts" / "notes.txt").write_text("y\n")
    r = cad(git_repo, "checkpoint")
    assert r.returncode != 0
    assert len(lines(r)) == 1 and "detached" in r.stderr


def test_command_without_project_is_one_line_error(plain_dir):
    r = cad(plain_dir, "checkpoint")
    assert r.returncode != 0
    assert len(lines(r)) == 1 and "init" in r.stderr
    assert not (plain_dir / "cad").exists()


# A model with no kernel: build() returns a stand-in with volume and a bbox.
STUB = '''
from types import SimpleNamespace as NS
PARAMS = {"w": 10.0}
def derive(P):
    return dict(P)
def build(P):
    w = P["w"]
    lo, hi = NS(X=0.0, Y=0.0, Z=0.0), NS(X=w, Y=10.0, Z=10.0)
    return NS(volume=w * 100.0, bounding_box=lambda: NS(min=lo, max=hi))
'''


def test_part_delta_on_checkpoint_revert_keep(plain_dir):
    p = open_project(plain_dir)
    (p.parts / "blk.py").write_text(STUB)
    pj = p.parts / "blk.params.json"
    checkpoint(p, "start")
    pj.write_text('{"w": 30}')
    line = checkpoint(p, "wider")
    assert "volume +2.0 cm³, bbox 10×10×10 → 30×10×10" in line, line
    try_(p, "narrow")
    pj.write_text('{"w": 20}')
    line = revert(p, "no")
    assert "volume +1.0 cm³, bbox 20×10×10 → 30×10×10" in line, line
    try_(p, "narrow again")
    pj.write_text('{"w": 25}')
    line = keep(p)
    assert "volume -0.5 cm³, bbox 30×10×10 → 25×10×10" in line, line


def test_no_part_delta_when_two_parts_change(plain_dir):
    p = open_project(plain_dir)
    for n in ("a", "b"):
        (p.parts / f"{n}.py").write_text(STUB)
    checkpoint(p, "start")
    for n in ("a", "b"):
        (p.parts / f"{n}.params.json").write_text('{"w": 12}')
    assert "volume" not in checkpoint(p, "both")


def test_drawing_writes_exact_sheet(plain_dir):
    assert cad(plain_dir, "init").returncode == 0
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "new_part.py"), "--project",
                        str(plain_dir), "--name", "spacer", "--params", "w=40,t=3"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = cad(plain_dir, "drawing", "spacer")
    assert r.returncode == 0 and len(lines(r)) == 1, r.stdout + r.stderr
    svg = (plain_dir / "cad" / "exports" / "spacer.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and ">top</text>" in svg


def test_serve_prints_one_line(plain_dir):
    assert cad(plain_dir, "init").returncode == 0
    (plain_dir / "cad" / "parts" / "blk.py").write_text(STUB)
    proc = subprocess.Popen([sys.executable, str(CAD), "serve", "--project", str(plain_dir)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8")
    try:
        first = proc.stdout.readline()
        assert first.startswith("bench: http://127.0.0.1:") and first.endswith("/  (1 part)\n"), first
    finally:
        proc.kill()
        proc.communicate()
