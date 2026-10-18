#!/usr/bin/env python3
"""bench_server.py -- the local live bench: a warm CAD kernel behind a tiny JSON API.

    python scripts/bench_server.py --project DIR [--port N]

prints one line (`bench: http://127.0.0.1:<port>/  (<n> parts)`) and serves
assets/live-bench.html plus the /api/* endpoints it calls on every slider move.
Binds 127.0.0.1 only. Builds are serialized; a build request older (by `seq`)
than the newest one received for that part is answered `stale` without building.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cadvc  # noqa: E402
import views  # noqa: E402
from cadproj import open_project  # noqa: E402
from partmodel import build_part, effective_params, load_model  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"
PART_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")
PLACEHOLDER = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>CAD Bench</title></head>"
               "<body><p>CAD Bench server is running; assets/live-bench.html is not installed.</p>"
               "</body></html>")
VC_OPS = {
    "checkpoint": lambda p, a: cadvc.checkpoint(p, a or None),
    "try": lambda p, a: cadvc.try_(p, a or "try"),
    "revert": lambda p, a: cadvc.revert(p, a or "reverted from bench"),
    "keep": lambda p, a: cadvc.keep(p),
    "back": lambda p, a: cadvc.back(p),
    "forward": lambda p, a: cadvc.forward(p),
    "goto": lambda p, a: cadvc.goto(p, a or ""),
}


class BadRequest(Exception):
    pass


def one_line(exc) -> str:
    """An exception as a single line: `Type: first line of message`."""
    lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip()]
    return f"{type(exc).__name__}: {lines[0]}" if lines else type(exc).__name__


def _log(msg):
    print(f"bench: {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ recipes

def _js_object(text):
    """A flat JS object literal (`{id:"w",min:1,...}`) as a dict, or None."""
    quoted = re.sub(r'([{,]\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', text)
    try:
        return json.loads(quoted)
    except ValueError:
        return None


def parse_recipe(source):
    """(label, params) from a recipe.js source; either may be None."""
    m = re.search(r'\blabel\s*:\s*"([^"]*)"', source)
    label = m.group(1) if m else None
    params = None
    m = re.search(r"\bparams\s*:\s*\[(.*?)\]", source, re.S)
    if m:
        objs = [_js_object(o) for o in re.findall(r"\{[^{}]*\}", m.group(1))]
        params = [o for o in objs if o is not None]
    return label, params


# ------------------------------------------------------------------- bench

class Bench:
    """The project plus the serialized, latest-wins build machinery."""

    def __init__(self, project):
        self.p = project
        self.build_lock = threading.Lock()
        self.seq_lock = threading.Lock()
        self.newest = {}  # part -> newest seq received
        self.thumbs = {}  # (sha, part) -> svg

    def _part_file(self, part):
        if not isinstance(part, str) or not PART_NAME.fullmatch(part):
            raise BadRequest(f"bad part name {part!r}")
        f = self.p.parts / f"{part}.py"
        if not f.is_file():
            raise BadRequest(f"no part named {part!r}")
        return f

    def part_names(self):
        if not self.p.parts.is_dir():
            return []
        return sorted(f.stem for f in self.p.parts.glob("*.py")
                      if PART_NAME.fullmatch(f.stem) and not f.stem.startswith("_"))

    def parts(self):
        out = []
        for name in self.part_names():
            rf = self.p.parts / f"{name}.recipe.js"
            src = rf.read_text(encoding="utf-8") if rf.is_file() else ""
            label, params = parse_recipe(src)
            if params is None:
                try:
                    model = load_model(self.p.parts / f"{name}.py")
                    params = [{"id": k, "val": v} for k, v in model.PARAMS.items()]
                except Exception as e:  # listing must survive a broken part
                    _log(f"{name}: {one_line(e)}")
                    params = []
            out.append({"name": name, "label": label or name.replace("_", " ").capitalize(),
                        "params": params, "recipe_js": src})
        return out

    def _params(self, model, part, over):
        P = effective_params(model, self.p.parts / f"{part}.params.json")
        if over:
            if not isinstance(over, dict):
                raise BadRequest("params must be an object")
            P.update({k: float(v) for k, v in over.items() if k in model.PARAMS})
        return P

    def build(self, req):
        part = req.get("part")
        f = self._part_file(part)
        seq = req.get("seq")
        if seq is not None:
            with self.seq_lock:
                if seq < self.newest.get(part, seq):
                    return {"ok": False, "stale": True}
                self.newest[part] = seq
        with self.build_lock:
            if seq is not None and seq < self.newest.get(part, seq):
                return {"ok": False, "stale": True}
            t0 = time.perf_counter()
            model = load_model(f)
            solid = build_part(model, self._params(model, part, req.get("params")))
            vs = views.project(solid)
            bb = solid.bounding_box()
            lo, hi = [bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]
            return {"ok": True, "views": vs, "volume": solid.volume,
                    "bbox": {"min": lo, "max": hi, "size": [b - a for a, b in zip(lo, hi)]},
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}

    def handoff(self, req):
        part = req.get("part")
        f = self._part_file(part)
        over = req.get("params") or {}
        if not isinstance(over, dict):
            raise BadRequest("params must be an object")
        known = load_model(f).PARAMS
        values = {k: float(v) for k, v in over.items() if k in known}
        out = self.p.parts / f"{part}.params.json"
        out.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
        res = {"ok": True, "path": str(out)}
        if cadvc.is_auto(self.p):
            try:
                res["checkpoint"] = cadvc.checkpoint(self.p, f"hand-off {part}")
            except cadvc.VCError as e:
                res["checkpoint_error"] = one_line(e)
        return res

    def vc(self, req):
        op = VC_OPS.get(req.get("op"))
        if op is None:
            raise BadRequest(f"unknown op {req.get('op')!r}")
        arg = req.get("arg")
        with self.build_lock:  # cad/ is rewritten: no build may read it halfway
            return {"ok": True, "line": op(self.p, str(arg) if arg is not None else None)}

    def history(self, part):
        if part and not PART_NAME.fullmatch(part):
            raise BadRequest(f"bad part name {part!r}")
        return cadvc.history(self.p, part or None)

    def thumb(self, sha, part):
        if not PART_NAME.fullmatch(part or ""):
            raise BadRequest(f"bad part name {part!r}")
        repo = cadvc.ensure_repo(self.p)
        full = cadvc._try_git(repo, "rev-parse", "--verify", "-q", f"{sha}^{{commit}}")
        if not full:
            raise BadRequest(f"unknown commit {sha!r}")
        key = (full.strip(), part)
        if key in self.thumbs:
            return self.thumbs[key]
        base = "parts" if repo.cad_rel == "." else f"{repo.cad_rel}/parts"
        src = cadvc._try_git(repo, "show", f"{key[0]}:{base}/{part}.py")
        if src is None:
            raise BadRequest(f"{part} does not exist at {sha}")
        pj = cadvc._try_git(repo, "show", f"{key[0]}:{base}/{part}.params.json")
        tmp = Path(tempfile.mkdtemp(prefix="cadthumb-"))
        try:
            (tmp / f"{part}.py").write_text(src, encoding="utf-8")
            if pj is not None:
                (tmp / f"{part}.params.json").write_text(pj, encoding="utf-8")
            with self.build_lock:
                model = load_model(tmp / f"{part}.py")
                solid = build_part(model, effective_params(model, tmp / f"{part}.params.json"))
                svg = views.sheet_svg(views.project(solid))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.thumbs[key] = svg
        return svg


# ----------------------------------------------------------------- handler

def _handler(bench):
    class Handler(BaseHTTPRequestHandler):
        server_version = "cad-bench"

        def log_message(self, fmt, *args):  # quiet: errors are logged one line each
            pass

        def _send(self, code, body, ctype):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj), "application/json")

        def _run(self, fn):
            try:
                res = fn()
            except BadRequest as e:
                _log(f"{self.path.split('?')[0]}: {one_line(e)}")
                self._json({"ok": False, "error": one_line(e).split(": ", 1)[-1]})
                return
            except Exception as e:  # a model or git failure must not kill the server
                _log(f"{self.path.split('?')[0]}: {one_line(e)}")
                self._json({"ok": False, "error": one_line(e)})
                return
            if isinstance(res, str):
                self._send(200, res, "image/svg+xml")
            else:
                self._json(res)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except ValueError:
                raise BadRequest("request body is not JSON")
            if not isinstance(req, dict):
                raise BadRequest("request body must be a JSON object")
            return req

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path in ("/", "/index.html"):
                page = ASSETS / "live-bench.html"
                html = page.read_text(encoding="utf-8") if page.is_file() else PLACEHOLDER
                self._send(200, html, "text/html")
            elif u.path == "/api/parts":
                self._run(bench.parts)
            elif u.path == "/api/history":
                self._run(lambda: bench.history(q.get("part")))
            elif u.path == "/api/thumb":
                self._run(lambda: bench.thumb(q.get("sha", ""), q.get("part", "")))
            else:
                self._json({"ok": False, "error": f"not found: {u.path}"}, 404)

        def do_POST(self):
            routes = {"/api/build": bench.build, "/api/handoff": bench.handoff,
                      "/api/vc": bench.vc}
            fn = routes.get(urlparse(self.path).path)
            if fn is None:
                self._json({"ok": False, "error": f"not found: {self.path}"}, 404)
                return
            self._run(lambda: fn(self._body()))

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # one line, never a traceback
        _log(one_line(sys.exc_info()[1]))


def serve(project_dir, port=0, open_browser=False):
    """Start the bench on 127.0.0.1 in a background thread; return (server, url)."""
    p = open_project(project_dir)
    bench = Bench(p)
    server = _Server(("127.0.0.1", port), _handler(bench))
    server.bench = bench
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    t = threading.Thread(target=server.serve_forever, name="cad-bench", daemon=True)
    t.start()
    server.thread = t
    if open_browser:
        webbrowser.open(url)
    return server, url


def main():
    ap = argparse.ArgumentParser(description="local live CAD bench")
    ap.add_argument("--project", default=os.getcwd(), help="project directory (default: cwd)")
    ap.add_argument("--port", type=int, default=0, help="port (default: any free port)")
    a = ap.parse_args()
    server, url = serve(Path(a.project), port=a.port)
    print(f"bench: {url}  ({len(server.bench.part_names())} parts)", flush=True)
    try:
        while server.thread.is_alive():
            server.thread.join(0.5)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
