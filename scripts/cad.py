#!/usr/bin/env python3
"""cad.py -- the plain-word front door to a project's cad/ folder.

    python scripts/cad.py <command> [args] [--project DIR]

    init                     create (or reopen) DIR/cad/ and its history
    checkpoint [name]        snapshot cad/ now
    try <idea>               start an experiment; the working version is untouched
    revert <reason>          abandon the experiment (kept on the graph with the reason)
    keep                     the experiment becomes the main version
    back | forward           step through checkpoints like undo / redo
    auto on|off              checkpoint automatically at every hand-off
    history [part] [--json]  one summary line (--json: the full list)
    serve [--port N]         run the live bench (blocks; prints its URL)
    sense <part>             flag redundant / no-effect / hard-coded dimensions
    drawing <part>           write cad/exports/<part>.svg (exact views)

Every command prints exactly one line on success. A refusal (detached HEAD,
nothing to keep, no project, ...) prints one line to stderr and exits 1.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("BREP_QUIET", "1")  # no kernel-import notice: one line per command

import cadvc  # noqa: E402
from cadproj import ProjectError, load_settings, open_project  # noqa: E402


def _project(a, create=False):
    root = Path(a.project).resolve()
    if not create and not (root / "cad").is_dir():
        raise ProjectError(f"no cad/ folder in {root}; run `cad.py init` there first")
    return open_project(root)


def _part_file(p, part):
    f = p.parts / f"{part}.py"
    if not f.is_file():
        raise ProjectError(f"no part named {part!r} in {p.parts}")
    return f


def _plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


# ------------------------------------------------------------------ commands

def cmd_init(a):
    p = _project(a, create=True)
    repo = cadvc.ensure_repo(p)
    n = len([f for f in p.parts.glob("*.py") if not f.stem.startswith("_")])
    where = "own repo" if repo.cad_rel == "." else f"repo {repo.top}"
    auto = "on" if load_settings(p).get("auto_checkpoint") else "off"
    return f"project {p.cad} · {_plural(n, 'part')} · history in {where} · auto-checkpoint {auto}"


def cmd_checkpoint(a):
    return cadvc.checkpoint(_project(a), " ".join(a.name) or None)


def cmd_try(a):
    return cadvc.try_(_project(a), " ".join(a.idea))


def cmd_revert(a):
    return cadvc.revert(_project(a), " ".join(a.reason))


def cmd_keep(a):
    return cadvc.keep(_project(a))


def cmd_back(a):
    return cadvc.back(_project(a))


def cmd_forward(a):
    return cadvc.forward(_project(a))


def cmd_auto(a):
    return cadvc.set_auto(_project(a), a.state == "on")


def cmd_history(a):
    rows = cadvc.history(_project(a), a.part)
    if a.json:
        return json.dumps(rows)
    n_cp = sum(1 for r in rows if r["track"] == "main")
    n_try = len({r["track"] for r in rows if r["track"] != "main"})
    latest = rows[0]["msg"] if rows else "none"
    return (f"history {a.part or 'all'}: {_plural(n_cp, 'checkpoint')}, "
            f"{_plural(n_try, 'try', 'tries')}, latest {latest}")


def cmd_serve(a):
    import bench_server  # lazy: pulls in the kernel
    _project(a)
    server, url = bench_server.serve(Path(a.project), port=a.port)
    print(f"bench: {url}  ({len(server.bench.part_names())} parts)", flush=True)
    try:
        while server.thread.is_alive():
            server.thread.join(0.5)
    except KeyboardInterrupt:
        server.shutdown()
    return None


def cmd_sense(a):
    p = _project(a)
    f = _part_file(p, a.part)
    import sense  # lazy: pulls in the kernel
    from partmodel import effective_params, load_model
    model = load_model(f)
    P = effective_params(model, p.parts / f"{a.part}.params.json")
    return sense.summarize(a.part, sense.sense(model, P))


def cmd_drawing(a):
    p = _project(a)
    f = _part_file(p, a.part)
    import views  # lazy: pulls in the kernel
    from partmodel import build_part, effective_params, load_model
    model = load_model(f)
    solid = build_part(model, effective_params(model, p.parts / f"{a.part}.params.json"))
    p.exports.mkdir(parents=True, exist_ok=True)
    out = p.exports / f"{a.part}.svg"
    # 310x200 cells: the sheet fills the shared bench's 620x400 drawing area exactly.
    out.write_text(views.sheet_svg(views.project(solid), cell_w=310, cell_h=200), encoding="utf-8")
    return f"drawing {a.part} → {out}"


# ----------------------------------------------------------------------- CLI

def _parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=argparse.SUPPRESS,
                        help="project directory holding cad/ (default: current directory)")
    ap = argparse.ArgumentParser(prog="cad.py", parents=[common],
                                 description="version and bench a project's cad/ folder")
    ap.set_defaults(project=os.getcwd())
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, parents=[common], **kw)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, help="create or reopen cad/ here")
    add("checkpoint", cmd_checkpoint, help="snapshot cad/ now").add_argument("name", nargs="*")
    add("try", cmd_try, help="start an experiment").add_argument("idea", nargs="+")
    add("revert", cmd_revert, help="abandon the experiment").add_argument("reason", nargs="+")
    add("keep", cmd_keep, help="keep the experiment")
    add("back", cmd_back, help="go to the previous checkpoint")
    add("forward", cmd_forward, help="go to the next checkpoint")
    add("auto", cmd_auto, help="auto-checkpoint on hand-off").add_argument("state", choices=("on", "off"))
    h = add("history", cmd_history, help="summary of checkpoints and tries")
    h.add_argument("part", nargs="?")
    h.add_argument("--json", action="store_true", help="print the full list as JSON")
    add("serve", cmd_serve, help="run the live bench").add_argument("--port", type=int, default=0)
    add("sense", cmd_sense, help="dimension sensing for one part").add_argument("part")
    add("drawing", cmd_drawing, help="write cad/exports/<part>.svg").add_argument("part")
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    a = _parser().parse_args(argv)
    try:
        line = a.fn(a)
    except (cadvc.VCError, ProjectError) as e:
        print(f"cad {a.cmd}: {str(e).splitlines()[0] if str(e) else type(e).__name__}",
              file=sys.stderr)
        return 1
    if line is not None:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
