"""Git-backed version control for a project's cad/ folder.

Checkpoints, experiments (try / revert / keep) and back / forward. Only paths
under cad/ are ever committed or rewritten; the user's other files, their index
entries, HEAD and the branch are left alone (HEAD moves only via checkpoint /
keep, which add a normal commit on the current branch).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cadproj import load_settings, save_settings

TRY_PREFIX = "refs/cad-bench/try/"
BASE_PREFIX = "refs/cad-bench/base/"
SETTINGS = ".cad-bench.json"  # per-machine settings: never staged or restored
_IN_PROGRESS = {
    "MERGE_HEAD": "merge",
    "REBASE_HEAD": "rebase",
    "rebase-merge": "rebase",
    "rebase-apply": "rebase",
    "CHERRY_PICK_HEAD": "cherry-pick",
    "REVERT_HEAD": "revert",
}


class VCError(Exception):
    pass


@dataclass
class Repo:
    top: Path
    cad_rel: str
    git_dir: Path = None


# --------------------------------------------------------------------------- git

def _git(repo, *args, env=None) -> str:
    """Run git in `repo` (a Repo, or a Path for pre-repo calls); return stdout."""
    cwd = repo.top if isinstance(repo, Repo) else repo
    full_env = None
    if env:
        full_env = dict(os.environ)
        full_env.update(env)
    r = subprocess.run(["git", *args], cwd=str(cwd), env=full_env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        lines = [ln for ln in (r.stderr or r.stdout).splitlines() if ln.strip()]
        raise VCError(lines[0] if lines else f"git {args[0]} failed")
    return r.stdout


def _try_git(repo, *args, env=None):
    try:
        return _git(repo, *args, env=env)
    except VCError:
        return None


@contextmanager
def _temp_index():
    d = tempfile.mkdtemp(prefix="cadvc-")
    try:
        yield {"GIT_INDEX_FILE": str(Path(d) / "index")}
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------------- repo

def ensure_repo(p) -> Repo:
    p.cad.mkdir(parents=True, exist_ok=True)
    top = _try_git(p.cad, "rev-parse", "--show-toplevel")
    if top is None:
        _git(p.cad, "init", "-q")
        if not _try_git(p.cad, "config", "user.name"):
            _git(p.cad, "config", "user.name", "cad-bench")
        if not _try_git(p.cad, "config", "user.email"):
            _git(p.cad, "config", "user.email", "cad-bench@localhost")
        top = _git(p.cad, "rev-parse", "--show-toplevel")
    prefix = _git(p.cad, "rev-parse", "--show-prefix").strip().rstrip("/")
    git_dir = _git(p.cad, "rev-parse", "--absolute-git-dir").strip()
    return Repo(top=Path(top.strip()), cad_rel=prefix or ".", git_dir=Path(git_dir))


def _head(repo):
    out = _try_git(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    return out.strip() if out else None


def _require_branch(repo):
    """Refuse (one line) on detached HEAD or an operation in progress."""
    if _try_git(repo, "symbolic-ref", "-q", "HEAD") is None:
        raise VCError("refusing: HEAD is detached; check out a branch first")
    for name, what in _IN_PROGRESS.items():
        if (repo.git_dir / name).exists():
            raise VCError(f"refusing: a {what} is in progress; finish or abort it first")


def _state_path(repo):
    return repo.git_dir / "cad-bench" / "state.json"


def _load_state(repo):
    f = _state_path(repo)
    return json.loads(f.read_text()) if f.exists() else {}


def _save_state(repo, s):
    f = _state_path(repo)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(s, indent=2) + "\n")


# ------------------------------------------------------------------ tree helpers

def _cad_spec(repo, commitish):
    return f"{commitish}^{{tree}}" if repo.cad_rel == "." else f"{commitish}:{repo.cad_rel}"


def _cad_tree(repo, commitish):
    out = _try_git(repo, "rev-parse", "--verify", "-q", _cad_spec(repo, commitish))
    return out.strip() if out else None


def _settings_path(repo):
    return SETTINGS if repo.cad_rel == "." else f"{repo.cad_rel}/{SETTINGS}"


def _cad_pathspec(repo):
    """cad/ minus the settings file, as top-relative pathspec args."""
    return [repo.cad_rel, f":(exclude){_settings_path(repo)}"]


def _snapshot(repo):
    """Top-level tree = HEAD with cad/ replaced by the working cad/; real index untouched."""
    with _temp_index() as env:
        if _head(repo):
            _git(repo, "read-tree", "HEAD", env=env)
        _git(repo, "add", "-A", "--", repo.cad_rel, env=env)
        _git(repo, "update-index", "--force-remove", "--", _settings_path(repo), env=env)
        return _git(repo, "write-tree", env=env).strip()


def _subtree(repo, top_tree):
    if repo.cad_rel == ".":
        return top_tree
    out = _try_git(repo, "rev-parse", "--verify", "-q", f"{top_tree}:{repo.cad_rel}")
    return out.strip() if out else None


def _n_changed(repo, a_tree, b_tree):
    """Number of files differing between two cad trees (None = empty)."""
    a_tree = a_tree or _empty_tree(repo)
    b_tree = b_tree or _empty_tree(repo)
    out = _git(repo, "diff-tree", "-r", "--name-only", a_tree, b_tree,
               "--", ".", f":(exclude){SETTINGS}")
    return len([ln for ln in out.splitlines() if ln])


def _empty_tree(repo):
    return _git(repo, "hash-object", "-t", "tree", "-w", "--stdin").strip()


def _restore(repo, cad_tree):
    """Make the working cad/ equal `cad_tree` (deleting extra files). HEAD/index untouched."""
    with _temp_index() as env:
        if repo.cad_rel == ".":
            _git(repo, "read-tree", cad_tree, env=env)
        else:
            _git(repo, "read-tree", f"--prefix={repo.cad_rel}/", cad_tree, env=env)
        _git(repo, "update-index", "--force-remove", "--", _settings_path(repo), env=env)
        target = set(_git(repo, "ls-files", "-z", env=env).split("\0")) - {""}
        current = set(_git(repo, "ls-files", "-z", "-c", "-o", "--exclude-standard",
                           "--", *_cad_pathspec(repo)).split("\0")) - {""}
        for rel in sorted(current - target):
            f = repo.top / rel
            if f.is_file() or f.is_symlink():
                f.unlink()
                _prune_empty(f.parent, repo)
        _git(repo, "checkout-index", "-a", "-f", env=env)


def _prune_empty(d, repo):
    stop = (repo.top / repo.cad_rel).resolve()
    keep = {stop / "parts", stop / "assemblies", stop / "exports"}
    d = d.resolve()
    while d != stop and stop in d.parents and d not in keep:
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent


def _summary(verb, name, n, sha):
    """The one-line result every command prints. Later tasks append to this."""
    return f"{verb} {name} · {n} file{'' if n == 1 else 's'} · {sha[:7]}"


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or "try"


# ---------------------------------------------------------------- experiments

def _try_commit(repo, state, msg):
    """Commit the working cad/ onto the active try ref; return (sha, parent)."""
    ref = TRY_PREFIX + state["slug"]
    tip = _try_git(repo, "rev-parse", "--verify", "-q", ref)
    parent = tip.strip() if tip else state["base"]
    tree = _snapshot(repo)
    args = ["commit-tree", tree, "-m", msg]
    if parent:
        args[2:2] = ["-p", parent]
    sha = _git(repo, *args).strip()
    _git(repo, "update-ref", ref, sha)
    return sha, parent


def _branch_commit(repo, msg):
    """Commit only cad/ on the current branch; other staged/unstaged changes stay put.

    Returns (sha, n_files) or (None, 0) when cad/ has nothing new.
    """
    # (`add` with an exclude pathspec naming an ignored file errors, so add cad/
    # whole -- the gitignored settings file is skipped -- and unstage it if an
    # older project still tracks it.)
    _git(repo, "add", "-A", "--", repo.cad_rel)
    if _git(repo, "ls-files", "--", _settings_path(repo)).strip():
        _try_git(repo, "reset", "-q", "--", _settings_path(repo))
    head = _head(repo)
    if head and _try_git(repo, "diff", "--cached", "--quiet", "HEAD", "--", *_cad_pathspec(repo)) is not None:
        return None, 0
    _git(repo, "commit", "-q", "-m", msg, "--", *_cad_pathspec(repo))
    sha = _head(repo)
    n = len([ln for ln in _git(repo, "show", "--name-only", "--format=", sha).splitlines() if ln])
    return sha, n


def _sense_note(p, names):
    """` · sense: N flags` for the parts among `names` (committed paths), or ""."""
    try:
        import sense as _sense  # lazy: pulls in the kernel
        from partmodel import effective_params, load_model
        stems = set()
        for nm in names:
            q = Path(nm)
            if q.parent.name == "parts":
                stems.add(q.name.split(".")[0])
        n = 0
        for stem in sorted(stems):
            f = p.parts / f"{stem}.py"
            if stem.startswith("_") or not f.is_file():
                continue  # deleted or private
            model = load_model(f)
            n += len(_sense.sense(model, effective_params(model, p.parts / f"{stem}.params.json")))
        return f" · sense: {n} flag{'' if n == 1 else 's'}" if n else ""
    except Exception:
        return ""


def checkpoint(p, name=None) -> str:
    repo = ensure_repo(p)
    _require_branch(repo)
    name = name or "checkpoint"
    state = _load_state(repo)
    if state.get("active"):
        sha, parent = _try_commit(repo, state, f"try: {name}")
        n = _n_changed(repo, parent and _cad_tree(repo, parent), _cad_tree(repo, sha))
        return _summary("try-checkpoint", name, n, sha)
    sha, n = _branch_commit(repo, f"cad: {name}")
    if state.pop("cursor", None) is not None:
        _save_state(repo, state)
    if sha is None:
        return _summary("unchanged", name, 0, _head(repo))
    names = _git(repo, "show", "--name-only", "--format=", sha).splitlines()
    return _summary("checkpoint", name, n, sha) + _sense_note(p, names)


def try_(p, idea) -> str:
    repo = ensure_repo(p)
    _require_branch(repo)
    state = _load_state(repo)
    if state.get("active"):
        raise VCError(f"already trying '{state['active']}'; keep or revert it first")
    slug = base_slug = _slug(idea)
    i = 2
    while any(_try_git(repo, "rev-parse", "--verify", "-q", pre + slug) is not None
              for pre in (TRY_PREFIX, BASE_PREFIX)):
        slug = f"{base_slug}-{i}"
        i += 1
    head = _head(repo)
    top_tree = _snapshot(repo)
    base_tree = _subtree(repo, top_tree)
    # Pin the starting snapshot under a ref so gc can never prune it before revert.
    args = ["commit-tree", top_tree, "-m", f"base: {idea}"] + (["-p", head] if head else [])
    _git(repo, "update-ref", BASE_PREFIX + slug, _git(repo, *args).strip())
    state.update(active=idea, slug=slug, base=head, base_tree=base_tree)
    state.pop("cursor", None)
    _save_state(repo, state)
    n = _n_changed(repo, head and _cad_tree(repo, head), base_tree)
    return _summary("trying", idea, n, head or base_tree)


def _clear_active(state):
    for k in ("active", "slug", "base", "base_tree"):
        state.pop(k, None)


def revert(p, reason) -> str:
    repo = ensure_repo(p)
    state = _load_state(repo)
    if not state.get("active"):
        raise VCError("nothing to revert: no experiment is active")
    sha, _ = _try_commit(repo, state, f"abandoned: {reason}")
    base_tree = state["base_tree"]
    n = _n_changed(repo, _cad_tree(repo, sha), base_tree)
    _restore(repo, base_tree)
    idea = state["active"]
    _clear_active(state)
    _save_state(repo, state)
    return _summary("reverted", idea, n, sha)


def keep(p) -> str:
    repo = ensure_repo(p)
    _require_branch(repo)
    state = _load_state(repo)
    if not state.get("active"):
        raise VCError("nothing to keep: no experiment is active")
    idea, slug = state["active"], state["slug"]
    sha, n = _branch_commit(repo, f"cad: keep {idea}")
    state.setdefault("kept", []).append(slug)
    _clear_active(state)
    _save_state(repo, state)
    return _summary("kept", idea, n, sha or _head(repo))


# --------------------------------------------------------------- back/forward

def _checkpoints(repo):
    if not _head(repo):
        return []
    return _git(repo, "log", "--format=%H", "HEAD", "--", repo.cad_rel).split()


def _move(p, step):
    repo = ensure_repo(p)
    state = _load_state(repo)
    if state.get("active"):
        raise VCError(f"experiment '{state['active']}' is active; keep or revert it first")
    cps = _checkpoints(repo)
    if not cps:
        raise VCError("no checkpoints yet")
    cur = state.get("cursor")
    i = cps.index(cur) if cur in cps else 0
    j = i + step
    if j < 0:
        return _summary("at newest", "checkpoint", 0, cps[0]) + " · nothing newer"
    if j >= len(cps):
        return _summary("at oldest", "checkpoint", 0, cps[-1]) + " · nothing older"
    # The cursor may sit off the checkpoint line (goto a try commit): compare the
    # working cad/ against where it actually is, not against cps[i].
    here = cur if cur and _cad_tree(repo, cur) else cps[i]
    return _go(repo, state, here, cps[j], "back to" if step > 0 else "forward to")


def _go(repo, state, here_sha, target_sha, verb):
    """Restore cad/ from `target_sha` and park the cursor there.

    Refuses when the working cad/ differs from `here_sha` (unsaved changes).
    """
    here = _subtree(repo, _snapshot(repo))
    if _n_changed(repo, here, _cad_tree(repo, here_sha)):
        raise VCError("cad/ has unsaved changes; checkpoint them before moving back/forward")
    target = _cad_tree(repo, target_sha)
    n = _n_changed(repo, here, target)
    _restore(repo, target)
    state["cursor"] = target_sha
    _save_state(repo, state)
    msg = _git(repo, "log", "-1", "--format=%s", target_sha).strip()
    return _summary(verb, msg, n, target_sha)


def back(p) -> str:
    return _move(p, +1)


def forward(p) -> str:
    return _move(p, -1)


def goto(p, sha) -> str:
    """Restore cad/ from any commit (checkpoint or try); back/forward continue from it."""
    repo = ensure_repo(p)
    state = _load_state(repo)
    if state.get("active"):
        raise VCError(f"experiment '{state['active']}' is active; keep or revert it first")
    out = _try_git(repo, "rev-parse", "--verify", "-q", f"{sha}^{{commit}}")
    target = out.strip() if out else None
    if not target or not _cad_tree(repo, target):
        raise VCError(f"no cad/ snapshot at {sha}")
    here = state.get("cursor") or _head(repo)
    if not here:
        raise VCError("no checkpoints yet")
    return _go(repo, state, here, target, "went to")


# --------------------------------------------------------------------- settings

def set_auto(p, on) -> str:
    s = load_settings(p)
    s["auto_checkpoint"] = bool(on)
    save_settings(p, s)
    return f"auto-checkpoint {'on' if on else 'off'}"


def is_auto(p) -> bool:
    return bool(load_settings(p).get("auto_checkpoint", False))


# ---------------------------------------------------------------------- history

_FMT = "%H%x1f%s%x1f%cI%x1f%P"


def _parse(out, track):
    rows = []
    for line in out.splitlines():
        if not line:
            continue
        sha, msg, when, parents = line.split("\x1f")
        if track == "main":
            kind = "kept" if msg.startswith("cad: keep ") else "checkpoint"
        else:
            kind = "abandoned" if msg.startswith("abandoned:") else "try"
        rows.append({"sha": sha, "msg": msg, "when": when, "kind": kind,
                     "track": track, "parent": parents.split()[0] if parents else None})
    return rows


def history(p, part=None) -> list:
    repo = ensure_repo(p)
    if part:
        sub = f"parts/{part}.*"
        spec = sub if repo.cad_rel == "." else f"{repo.cad_rel}/{sub}"
    else:
        spec = repo.cad_rel
    head = _head(repo)
    refs = _git(repo, "for-each-ref", "--format=%(refname)", TRY_PREFIX).split()
    rows = []
    if head:
        rows += _parse(_git(repo, "log", f"--format={_FMT}", "HEAD", "--", spec), "main")
    for ref in refs:
        args = ["log", f"--format={_FMT}", ref] + (["--not", "HEAD"] if head else [])
        if part:
            args += ["--", spec]
        rows += _parse(_git(repo, *args), ref[len(TRY_PREFIX):])
    tips = (["HEAD"] if head else []) + refs
    order = _git(repo, "log", "--topo-order", "--format=%H", *tips).split() if tips else []
    rank = {sha: i for i, sha in enumerate(order)}
    rows.sort(key=lambda r: rank.get(r["sha"], len(rank)))
    return rows
