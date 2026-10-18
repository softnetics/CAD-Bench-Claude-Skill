import subprocess

import pytest

from cadproj import open_project
from cadvc import (
    VCError,
    back,
    checkpoint,
    ensure_repo,
    forward,
    history,
    is_auto,
    keep,
    revert,
    set_auto,
    try_,
)


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return r.stdout


@pytest.fixture(params=["git_repo", "plain_dir"])
def any_dir(request):
    return request.param, request.getfixturevalue(request.param)


def test_ensure_repo_outside_git_inits_in_cad(plain_dir):
    p = open_project(plain_dir)
    repo = ensure_repo(p)
    assert (p.cad / ".git").exists()
    assert not (plain_dir / ".git").exists()
    assert repo.cad_rel == "."
    assert repo.top.resolve() == p.cad.resolve()


def test_ensure_repo_inside_git_uses_existing(git_repo):
    p = open_project(git_repo)
    repo = ensure_repo(p)
    assert not (p.cad / ".git").exists()
    assert repo.cad_rel == "cad"
    assert repo.top.resolve() == git_repo.resolve()


def test_checkpoint_commits_only_cad(any_dir):
    kind, d = any_dir
    (d / "firmware").mkdir(exist_ok=True)
    p = open_project(d)
    (p.parts / "a.py").write_text("a = 1\n")
    (d / "firmware" / "main.c").write_text("int main(void) { return 1; }\n")
    line = checkpoint(p, "first")
    assert "\n" not in line and line.startswith("checkpoint first")
    top = ensure_repo(p).top
    names = git(top, "show", "--name-only", "--format=", "HEAD").split()
    if kind == "git_repo":
        assert names and all(n.startswith("cad/") for n in names)
        assert "cad/parts/a.py" in names
        assert "firmware/main.c" in git(top, "diff", "--name-only")
    else:
        assert "parts/a.py" in names
        assert not any("firmware" in n for n in names)
    assert (d / "firmware" / "main.c").read_text() == "int main(void) { return 1; }\n"


def test_non_cad_changes_untouched(git_repo):
    p = open_project(git_repo)
    fw = git_repo / "firmware"
    (fw / "main.c").write_text("int main(void) { return 2; }\n")
    git(git_repo, "add", "firmware/main.c")
    (fw / "main.c").write_text("int main(void) { return 3; }\n")
    (fw / "extra.h").write_text("#define X 1\n")
    git(git_repo, "add", "firmware/extra.h")
    (fw / "untracked.txt").write_text("loose\n")
    before = (git(git_repo, "diff", "--", "firmware"),
              git(git_repo, "diff", "--cached", "--", "firmware"),
              (fw / "untracked.txt").read_text())

    (p.parts / "a.py").write_text("a = 1\n")
    checkpoint(p, "one")
    try_(p, "thicker wall")
    (p.parts / "a.py").write_text("a = 2\n")
    checkpoint(p, "experiment")
    revert(p, "no good")
    try_(p, "fillet")
    (p.parts / "a.py").write_text("a = 3\n")
    keep(p)

    after = (git(git_repo, "diff", "--", "firmware"),
             git(git_repo, "diff", "--cached", "--", "firmware"),
             (fw / "untracked.txt").read_text())
    assert after == before


def test_try_does_not_move_head_or_branch(git_repo):
    p = open_project(git_repo)
    (p.parts / "a.py").write_text("a = 1\n")
    checkpoint(p, "base")
    head = git(git_repo, "rev-parse", "HEAD")
    branch = git(git_repo, "symbolic-ref", "HEAD")
    try_(p, "idea")
    (p.parts / "a.py").write_text("a = 2\n")
    checkpoint(p, "e1")
    (p.parts / "a.py").write_text("a = 3\n")
    checkpoint(p, "e2")
    assert git(git_repo, "rev-parse", "HEAD") == head
    assert git(git_repo, "symbolic-ref", "HEAD") == branch
    refs = git(git_repo, "for-each-ref", "--format=%(refname)", "refs/cad-bench/try/")
    assert refs.strip() == "refs/cad-bench/try/idea"
    assert "try: e2" in git(git_repo, "log", "-1", "--format=%s", "refs/cad-bench/try/idea")


def test_revert_removes_new_files_and_keeps_them_recoverable(any_dir):
    _, d = any_dir
    p = open_project(d)
    (p.parts / "a.py").write_text("a = 1\n")
    checkpoint(p, "base")
    try_(p, "extra part")
    (p.parts / "new.py").write_text("n = 1\n")
    (p.parts / "a.py").write_text("a = 99\n")
    line = revert(p, "too thin")
    assert "\n" not in line
    assert not (p.parts / "new.py").exists()
    assert (p.parts / "a.py").read_text() == "a = 1\n"
    top = ensure_repo(p).top
    ab = [h for h in history(p) if h["kind"] == "abandoned"]
    assert len(ab) == 1 and "too thin" in ab[0]["msg"]
    files = git(top, "ls-tree", "-r", "--name-only", ab[0]["sha"])
    assert "new.py" in files
    assert ab[0]["track"] == "extra-part"


def test_keep_lands_on_branch(git_repo):
    p = open_project(git_repo)
    (p.parts / "a.py").write_text("a = 1\n")
    checkpoint(p, "base")
    try_(p, "bigger")
    (p.parts / "a.py").write_text("a = 2\n")
    line = keep(p)
    assert line.startswith("kept bigger")
    assert git(git_repo, "log", "-1", "--format=%s").startswith("cad: keep")
    assert git(git_repo, "show", "HEAD:cad/parts/a.py") == "a = 2\n"
    assert history(p)[0]["kind"] == "kept"
    # no longer active: a checkpoint goes to the branch again
    (p.parts / "a.py").write_text("a = 3\n")
    checkpoint(p, "after")
    assert git(git_repo, "log", "-1", "--format=%s") == "cad: after\n"


def test_back_forward_round_trip(any_dir):
    _, d = any_dir
    p = open_project(d)
    top = ensure_repo(p).top
    for i in (1, 2, 3):
        (p.parts / "a.py").write_text(f"a = {i}\n")
        checkpoint(p, f"c{i}")
    head = git(top, "rev-parse", "HEAD")
    back(p)
    assert (p.parts / "a.py").read_text() == "a = 2\n"
    back(p)
    assert (p.parts / "a.py").read_text() == "a = 1\n"
    assert git(top, "rev-parse", "HEAD") == head
    forward(p)
    assert (p.parts / "a.py").read_text() == "a = 2\n"
    forward(p)
    assert (p.parts / "a.py").read_text() == "a = 3\n"
    line = forward(p)
    assert "\n" not in line and "newest" in line
    assert (p.parts / "a.py").read_text() == "a = 3\n"
    assert git(top, "rev-parse", "HEAD") == head


def test_back_removes_files_added_later(git_repo):
    p = open_project(git_repo)
    (p.parts / "a.py").write_text("a = 1\n")
    checkpoint(p, "c1")
    (p.parts / "b.py").write_text("b = 1\n")
    checkpoint(p, "c2")
    back(p)
    assert not (p.parts / "b.py").exists()
    forward(p)
    assert (p.parts / "b.py").read_text() == "b = 1\n"


def test_back_refuses_with_unsaved_changes(git_repo):
    p = open_project(git_repo)
    for i in (1, 2):
        (p.parts / "a.py").write_text(f"a = {i}\n")
        checkpoint(p, f"c{i}")
    (p.parts / "a.py").write_text("a = unsaved\n")
    with pytest.raises(VCError):
        back(p)
    assert (p.parts / "a.py").read_text() == "a = unsaved\n"


def test_refuses_on_detached_head(git_repo):
    p = open_project(git_repo)
    (p.parts / "a.py").write_text("a = 1\n")
    checkpoint(p, "base")
    git(git_repo, "checkout", "-q", "--detach")
    (p.parts / "a.py").write_text("a = 2\n")
    refs_before = git(git_repo, "for-each-ref")
    head_before = git(git_repo, "rev-parse", "HEAD")
    for fn in (lambda: checkpoint(p, "x"), lambda: try_(p, "x"), lambda: keep(p)):
        with pytest.raises(VCError) as e:
            fn()
        assert "detached" in str(e.value) and "\n" not in str(e.value)
    assert git(git_repo, "for-each-ref") == refs_before
    assert git(git_repo, "rev-parse", "HEAD") == head_before
    gitdir = git_repo / ".git"
    assert not (gitdir / "cad-bench" / "state.json").exists()


def test_refuses_during_merge(git_repo):
    p = open_project(git_repo)
    (p.parts / "a.py").write_text("a = 1\n")
    checkpoint(p, "base")
    head = git(git_repo, "rev-parse", "HEAD").strip()
    (git_repo / ".git" / "MERGE_HEAD").write_text(head + "\n")
    with pytest.raises(VCError) as e:
        checkpoint(p, "x")
    assert "merge" in str(e.value)


def test_auto_setting_persists(plain_dir):
    p = open_project(plain_dir)
    assert is_auto(p) is False
    assert "\n" not in set_auto(p, True)
    assert is_auto(open_project(plain_dir)) is True


def test_history_filters_by_part(git_repo):
    p = open_project(git_repo)
    (p.parts / "a.py").write_text("a = 1\n")
    checkpoint(p, "a1")
    (p.parts / "b.py").write_text("b = 1\n")
    checkpoint(p, "b1")
    try_(p, "tweak a")
    (p.parts / "a.py").write_text("a = 2\n")
    checkpoint(p, "a2")
    all_msgs = [h["msg"] for h in history(p)]
    assert all_msgs[:3] == ["try: a2", "cad: b1", "cad: a1"]
    assert "init" not in all_msgs
    a_msgs = [h["msg"] for h in history(p, "a")]
    assert a_msgs == ["try: a2", "cad: a1"]
    assert [h["msg"] for h in history(p, "b")] == ["cad: b1"]
    h = history(p)[0]
    assert h["kind"] == "try" and h["track"] == "tweak-a" and h["parent"]
    assert set(h) == {"sha", "msg", "when", "kind", "track", "parent"}
    assert history(p)[1]["track"] == "main"
