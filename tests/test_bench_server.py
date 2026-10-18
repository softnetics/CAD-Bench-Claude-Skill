import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from bench_server import serve
from cadproj import open_project
from cadvc import checkpoint, ensure_repo, history, set_auto

REPO = Path(__file__).resolve().parent.parent

# Build depends on the params, so a too-big fillet makes the kernel raise.
SPACER_BUILD = '''

def build(P):
    part = B.Box(P["w"], P["w"], 10, align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
    return B.fillet(part.edges().filter_by(B.Axis.Z), radius=P["t"])
'''


@pytest.fixture
def bench(plain_dir):
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "new_part.py"), "--project", str(plain_dir),
         "--name", "spacer", "--params", "w=40,t=3"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    p = open_project(plain_dir)
    model = p.parts / "spacer.py"
    src = model.read_text(encoding="utf-8")
    model.write_text(src.replace("\n\ndef main():", SPACER_BUILD + "\n\ndef main():"),
                     encoding="utf-8")
    server, url = serve(plain_dir, port=0)
    yield p, url
    server.shutdown()
    server.server_close()


def get(url, path):
    with urllib.request.urlopen(url + path.lstrip("/"), timeout=60) as r:
        body = r.read().decode("utf-8")
        return json.loads(body) if r.headers.get_content_type() == "application/json" else body


def post(url, path, payload):
    req = urllib.request.Request(url + path.lstrip("/"), data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def test_parts_listing(bench):
    _, url = bench
    parts = get(url, "/api/parts")
    assert [x["name"] for x in parts] == ["spacer"]
    spacer = parts[0]
    assert spacer["label"] == "Spacer"
    assert [q["id"] for q in spacer["params"]] == ["w", "t"]
    assert spacer["params"][0]["val"] == 40 and spacer["params"][0]["step"] == 0.5
    assert 'label:"Spacer"' in spacer["recipe_js"]


def test_parts_listing_carries_current_values(bench):
    p, url = bench
    assert get(url, "/api/parts")[0]["values"] == {"w": 40.0, "t": 3.0}
    (p.parts / "spacer.params.json").write_text('{"t": 0.43}', encoding="utf-8")
    assert get(url, "/api/parts")[0]["values"] == {"w": 40.0, "t": 0.43}


def test_build_returns_views_fast(bench):
    _, url = bench
    first = post(url, "/api/build", {"part": "spacer", "params": {"w": 40, "t": 3}, "seq": 1})
    assert first["ok"], first
    t0 = time.perf_counter()
    second = post(url, "/api/build", {"part": "spacer", "params": {"w": 41.3, "t": 3}, "seq": 2})
    elapsed = time.perf_counter() - t0
    assert second["ok"], second
    assert set(second["views"]) == {"top", "front", "side", "iso"}
    assert second["views"]["top"]["vis"]
    assert second["volume"] > 0
    assert second["bbox"]["size"][0] == pytest.approx(41.3, abs=1e-6)
    assert elapsed < 0.5, f"second build took {elapsed:.3f}s"


def test_build_error_is_reported_not_fatal(bench):
    _, url = bench
    bad = post(url, "/api/build", {"part": "spacer", "params": {"w": 40, "t": 30}, "seq": 1})
    assert bad["ok"] is False
    assert bad["error"] and "\n" not in bad["error"]
    good = post(url, "/api/build", {"part": "spacer", "params": {"w": 40, "t": 3}, "seq": 2})
    assert good["ok"] is True


def test_unknown_part_is_reported(bench):
    _, url = bench
    r = post(url, "/api/build", {"part": "../nope", "params": {}, "seq": 1})
    assert r["ok"] is False and "\n" not in r["error"]


def test_stale_request_skipped(bench):
    _, url = bench
    newer = post(url, "/api/build", {"part": "spacer", "params": {"w": 40, "t": 3}, "seq": 2})
    older = post(url, "/api/build", {"part": "spacer", "params": {"w": 30, "t": 3}, "seq": 1})
    assert newer["ok"] is True
    assert older == {"ok": False, "stale": True}


def test_handoff_writes_exact_params(bench):
    p, url = bench
    r = post(url, "/api/handoff", {"part": "spacer", "params": {"t": 0.4}})
    assert r["ok"] is True
    f = p.parts / "spacer.params.json"
    assert Path(r["path"]).resolve() == f.resolve()
    text = f.read_text(encoding="utf-8")
    assert "0.4" in text and "0.40" not in text
    assert json.loads(text) == {"t": 0.4}
    assert not history(p)  # auto-checkpoint is off by default


def test_handoff_checkpoints_when_auto_on(bench):
    p, url = bench
    set_auto(p, True)
    r = post(url, "/api/handoff", {"part": "spacer", "params": {"w": 52.4}})
    assert r["ok"] is True and "checkpoint" in r
    assert len(history(p)) == 1


def test_vc_does_not_auto_checkpoint(bench):
    p, url = bench
    set_auto(p, True)
    model = p.parts / "spacer.py"
    checkpoint(p, "one")
    model.write_text(model.read_text(encoding="utf-8") + "\n# two\n", encoding="utf-8")
    checkpoint(p, "two")
    r = post(url, "/api/vc", {"op": "back"})
    assert r["ok"] is True and "\n" not in r["line"]
    assert "# two" not in model.read_text(encoding="utf-8")
    hist = get(url, "/api/history?part=spacer")
    assert [h["msg"] for h in hist] == ["cad: two", "cad: one"]
    r = post(url, "/api/vc", {"op": "goto", "arg": hist[0]["sha"]})
    assert r["ok"] is True
    assert "# two" in model.read_text(encoding="utf-8")
    assert len(history(p)) == 2


def test_vc_error_is_one_line(bench):
    _, url = bench
    r = post(url, "/api/vc", {"op": "keep"})
    assert r["ok"] is False and r["error"] and "\n" not in r["error"]
    r = post(url, "/api/vc", {"op": "frobnicate"})
    assert r["ok"] is False


def test_thumb_builds_from_commit_files(bench):
    p, url = bench
    (p.parts / "spacer.params.json").write_text(json.dumps({"w": 40}), encoding="utf-8")
    checkpoint(p, "wide")
    sha = history(p)[0]["sha"]
    (p.parts / "spacer.params.json").write_text(json.dumps({"w": 20}), encoding="utf-8")
    model = p.parts / "spacer.py"
    model.write_text(model.read_text(encoding="utf-8").replace(
        'part = B.Box(P["w"]', 'raise ValueError("broken")\n    part = B.Box(P["w"]'),
        encoding="utf-8")
    svg = get(url, f"/api/thumb?sha={sha}&part=spacer")
    assert svg.startswith("<svg") and ">top<" in svg
    assert get(url, f"/api/thumb?sha={sha}&part=spacer") == svg  # cached


def test_index_served(bench):
    _, url = bench
    with urllib.request.urlopen(url, timeout=30) as r:
        assert r.headers.get_content_type() == "text/html"
        assert b"<html" in r.read().lower()


def test_refuses_cross_site_requests(bench):
    p, url = bench
    base = url.rstrip("/")
    body = json.dumps({"part": "spacer", "params": {"w": 1}}).encode("utf-8")
    simple = urllib.request.Request(base + "/api/handoff", data=body, method="POST",
                                    headers={"Content-Type": "text/plain"})
    rebound = urllib.request.Request(base + "/api/handoff", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Host": "evil.example:" + url.split(":")[-1].rstrip("/")})
    rebound_get = urllib.request.Request(base + "/api/history", headers={"Host": "evil.example"})
    for req in (simple, rebound, rebound_get):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=30)
        assert e.value.code == 403
    assert not (p.parts / "spacer.params.json").exists()
    local = urllib.request.Request(base + "/api/parts",
                                   headers={"Host": "localhost:" + url.split(":")[-1].rstrip("/")})
    with urllib.request.urlopen(local, timeout=30) as r:
        assert r.status == 200


def test_binds_localhost_only(bench, plain_dir):
    _, url = bench
    assert urllib.parse.urlparse(url).hostname == "127.0.0.1"
    server, _ = serve(plain_dir, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.shutdown()
        server.server_close()


def test_cli_prints_one_line(plain_dir):
    open_project(plain_dir)
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "scripts" / "bench_server.py"), "--project", str(plain_dir),
         "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline()
        assert line.startswith("bench: http://127.0.0.1:") and line.rstrip().endswith("/  (0 parts)")
    finally:
        proc.kill()
        proc.wait()
