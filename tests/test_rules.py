"""Confirmed rules: parse, bind roles, carry sizes, check, scopes."""
import datetime
import textwrap

import pytest

import assembly as A
import rules as R

SHAFT = '''
import brep as B
import assembly as A
PARAMS = {"shaft_d": 3.0, "shaft_len": 12.0}
def derive(P):
    d = dict(P); d["tip"] = P["shaft_len"]; return d
def build(P):
    return B.Cylinder(P["shaft_d"] / 2, P["shaft_len"],
                      align=(B.Align.CENTER, B.Align.CENTER, B.Align.MIN))
def connectors(P):
    return {"tip": A.axis((0, 0, P["shaft_len"]), z=(0, 0, 1))}
'''

WHEEL = '''
import brep as B
import assembly as A
PARAMS = {"tyre_d": 40.0, "w": 6.0, "bore_d": 2.0, "hub_len": 10.0, "spokes": 5}
def derive(P):
    d = dict(P); d["wall"] = (P["tyre_d"] - P["bore_d"]) / 2; return d
def build(P):
    w = B.Cylinder(P["tyre_d"] / 2, P["w"],
                   align=(B.Align.CENTER, B.Align.CENTER, B.Align.MAX))
    return w - B.Pos(0, 0, -P["w"] / 2) * B.Cylinder(P["bore_d"] / 2, P["w"] + 2)
def connectors(P):
    return {"hub": A.axis((0, 0, 0), z=(0, 0, 1))}
'''

HUB_RULES = """\
kind: wheel hub
purpose: A wheel pressed onto a motor shaft.
roles: wheel, shaft
confirmed: 2026-10-18
rule: wheel.bore_d = shaft.shaft_d + 0.1     # printed holes shrink: presses on
rule: shaft.shaft_len >= wheel.hub_len       # the shaft reaches through the hub
"""


@pytest.fixture
def proj(tmp_path, monkeypatch):
    (tmp_path / "shaft.py").write_text(SHAFT)
    (tmp_path / "wheel.py").write_text(WHEEL)
    (tmp_path / "rules").mkdir()
    world = tmp_path / "world"
    (world / "rules").mkdir(parents=True)
    monkeypatch.setenv("CAD_BENCH_LIBRARY", str(world))
    return tmp_path


def asm_of(proj, shaft_d=3.0, **kw):
    asm = A.Assembly("t", path=proj / "t.py")
    asm.add("motor", part="shaft", params={"shaft_d": shaft_d, **kw})
    asm.add("wheel", part="wheel")
    asm.join("motor.tip", "wheel.hub", "wheel", flip=True)
    return asm


# ---------------------------------------------------------------- files

def test_load_rule_file(proj):
    f = proj / "rules" / "hub.rules"
    f.write_text(HUB_RULES)
    rf = R.load_rule_file(f)
    assert rf.kind == "wheel hub"
    assert rf.roles == ["wheel", "shaft"]
    assert rf.confirmed == "2026-10-18"
    assert [r.why for r in rf.rules][0] == "printed holes shrink: presses on"
    assert rf.rules[1].text == "shaft.shaft_len >= wheel.hub_len"


def test_bind_roles():
    assert R.bind("wheel.bore_d = shaft.shaft_d + 0.1",
                  {"wheel": "wheel_l", "shaft": "motor_l"}) == \
        "wheel_l.bore_d = motor_l.shaft_d + 0.1"
    with pytest.raises(R.RuleError, match="role 'shaft'"):
        R.bind("wheel.bore_d = shaft.shaft_d", {"wheel": "w"})


def test_rules_dirs(tmp_path, monkeypatch):
    assert R.project_rules_dir(tmp_path / "cad" / "assemblies" / "bot.py") == \
        tmp_path / "cad" / "rules"
    assert R.project_rules_dir(tmp_path / "models" / "bot.py") == \
        tmp_path / "models" / "rules"
    monkeypatch.delenv("CAD_BENCH_LIBRARY", raising=False)
    assert R.world_rules_dir().parts[-2:] == ("library", "rules")


def test_project_overrides_world(proj):
    (proj / "world" / "rules" / "hub.rules").write_text(
        HUB_RULES.replace("+ 0.1", "+ 0.3"))
    assert "0.3" in R.find_kind("wheel hub", proj / "rules",
                                R.world_rules_dir()).rules[0].text
    (proj / "rules" / "hub.rules").write_text(HUB_RULES)
    assert "0.1" in R.find_kind("Wheel Hub", proj / "rules",
                                R.world_rules_dir()).rules[0].text


# ---------------------------------------------------------------- applying

def test_set_rule_carries_the_size(proj):
    (proj / "rules" / "hub.rules").write_text(HUB_RULES)
    for d in (3.0, 4.0):
        asm = asm_of(proj, shaft_d=d)
        asm.use_rules("wheel hub", wheel="wheel", shaft="motor")
        s = asm.solve()
        assert asm.instances["wheel"].P["bore_d"] == pytest.approx(d + 0.1)
        assert all(r.ok for r in s.rule_results) and len(s.rule_results) == 2
        assert s.warnings == []


def test_broken_check_warns(proj):
    (proj / "rules" / "hub.rules").write_text(HUB_RULES)
    asm = asm_of(proj, shaft_len=8.0)
    asm.use_rules("wheel hub", wheel="wheel", shaft="motor")
    s = asm.solve()
    assert any(w.startswith("rule broken: motor.shaft_len >= wheel.hub_len")
               and "8 vs 10" in w for w in s.warnings)


def test_world_rules_are_used_when_project_has_none(proj):
    (proj / "world" / "rules" / "hub.rules").write_text(HUB_RULES)
    asm = asm_of(proj)
    asm.use_rules("wheel hub", wheel="wheel", shaft="motor")
    asm.solve()
    assert asm.instances["wheel"].P["bore_d"] == pytest.approx(3.1)


def test_unconfirmed_rules_are_ignored_and_counted(proj):
    (proj / "rules" / "hub.rules").write_text(HUB_RULES.replace("confirmed: 2026-10-18\n", ""))
    asm = asm_of(proj)
    asm.use_rules("wheel hub", wheel="wheel", shaft="motor")
    asm.rule("wheel.w >= 5")                              # not confirmed either
    s = asm.solve()
    assert asm.instances["wheel"].P["bore_d"] == 2.0
    assert s.rules_ignored == 3 and s.rule_results == []


def test_inline_confirmed_rule_and_derived_values(proj):
    asm = asm_of(proj)
    asm.rule("wheel.wall >= 25", why="thick enough", confirmed=True)
    s = asm.solve()
    assert any("wheel.wall >= 25" in w and "(thick enough)" in w for w in s.warnings)


def test_rules_chain_in_dependency_order(proj):
    asm = asm_of(proj)
    asm.rule("wheel.hub_len = wheel.bore_d * 2", confirmed=True)
    asm.rule("wheel.bore_d = motor.shaft_d + 1", confirmed=True)
    asm.solve()
    assert asm.instances["wheel"].P["hub_len"] == pytest.approx(8.0)


def test_cycle_is_an_error(proj):
    asm = asm_of(proj)
    asm.rule("wheel.hub_len = wheel.bore_d * 2", confirmed=True)
    asm.rule("wheel.bore_d = wheel.hub_len / 2", confirmed=True)
    with pytest.raises(R.RuleError, match="cycle"):
        asm.solve()


def test_rule_set_param_also_given_in_add_is_an_error(proj):
    asm = A.Assembly("t", path=proj / "t.py")
    asm.add("motor", part="shaft")
    asm.add("wheel", part="wheel", params={"bore_d": 3.0})
    asm.rule("wheel.bore_d = motor.shaft_d + 0.1", confirmed=True)
    with pytest.raises(R.RuleError, match="wheel.bore_d"):
        asm.solve()


def test_unknown_names_are_reported(proj):
    asm = asm_of(proj)
    asm.rule("wheel.nope >= 1", confirmed=True)
    with pytest.raises(R.RuleError, match="wheel.nope"):
        asm.solve()
    asm = asm_of(proj)
    asm.rule("ghost.bore_d = 1", confirmed=True)
    with pytest.raises(R.RuleError, match="ghost"):
        asm.solve()


def test_set_target_must_be_a_parameter(proj):
    asm = asm_of(proj)
    asm.rule("wheel.wall = 3", confirmed=True)
    with pytest.raises(R.RuleError, match="not a parameter"):
        asm.solve()


def test_unsafe_expressions_rejected(proj):
    asm = asm_of(proj)
    asm.rule("wheel.w >= __import__('os').getpid()", confirmed=True)
    with pytest.raises(R.RuleError):
        asm.solve()


def test_missing_kind_is_an_error(proj):
    asm = asm_of(proj)
    asm.use_rules("gearbox", a="motor")
    with pytest.raises(R.RuleError, match="gearbox"):
        asm.solve()


def test_list_cli_one_line(proj, capsys):
    (proj / "rules" / "hub.rules").write_text(HUB_RULES)
    (proj / "world" / "rules" / "x.rules").write_text(
        HUB_RULES.replace("wheel hub", "motor mount").replace("confirmed: 2026-10-18\n", ""))
    assert R.main(["list", str(proj / "t.py")]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["rules: project: wheel hub; worldwide: motor mount (unconfirmed)"]


# ---------------------------------------------------------------- confirmed

@pytest.mark.parametrize("value", ["no", "pending", "yes", "2026-13-45", "18/10/2026"])
def test_confirmed_must_be_a_date_or_true(proj, value):
    (proj / "rules" / "hub.rules").write_text(
        HUB_RULES.replace("confirmed: 2026-10-18", f"confirmed: {value}"))
    asm = asm_of(proj)
    asm.use_rules("wheel hub", wheel="wheel", shaft="motor")
    asm.rule("wheel.w = 9", confirmed=value)
    s = asm.solve()
    assert asm.instances["wheel"].P["bore_d"] == 2.0 and asm.instances["wheel"].P["w"] == 6.0
    assert s.rule_results == [] and s.rules_ignored == 3
    notes = [w for w in s.warnings if "confirmed" in w]
    assert len(notes) == 1, s.warnings
    assert "hub.rules" in notes[0] and "t.py (inline)" in notes[0] and value in notes[0]


@pytest.mark.parametrize("value", ["2026-10-18", "true", "True"])
def test_a_date_or_true_confirms_a_file(proj, value):
    (proj / "rules" / "hub.rules").write_text(
        HUB_RULES.replace("confirmed: 2026-10-18", f"confirmed: {value}"))
    asm = asm_of(proj)
    asm.use_rules("wheel hub", wheel="wheel", shaft="motor")
    asm.rule("wheel.w = 9", confirmed=True)
    asm.rule("wheel.tyre_d = 50", confirmed="2026-10-18")
    asm.rule("wheel.hub_len = 11", confirmed=datetime.date(2026, 10, 18))
    s = asm.solve()
    assert asm.instances["wheel"].P["bore_d"] == pytest.approx(3.1)
    assert asm.instances["wheel"].P["w"] == 9 and asm.instances["wheel"].P["tyre_d"] == 50
    assert asm.instances["wheel"].P["hub_len"] == 11
    assert s.rules_ignored == 0 and not [w for w in s.warnings if "confirmed" in w]


def test_list_marks_a_bad_confirmed_value_unconfirmed(proj, capsys):
    (proj / "rules" / "hub.rules").write_text(
        HUB_RULES.replace("confirmed: 2026-10-18", "confirmed: no"))
    assert R.main(["list", str(proj / "t.py")]) == 0
    assert "wheel hub (unconfirmed)" in capsys.readouterr().out


# ---------------------------------------------------------------- values

def test_int_parameter_stays_int(proj):
    asm = asm_of(proj)
    asm.rule("wheel.spokes = motor.shaft_d + 3", confirmed=True)
    asm.solve()
    v = asm.instances["wheel"].P["spokes"]
    assert v == 6 and type(v) is int


def test_int_parameter_set_to_a_fraction_is_an_error(proj):
    asm = asm_of(proj)
    asm.rule("wheel.spokes = motor.shaft_d / 2", confirmed=True)
    with pytest.raises(R.RuleError, match="wheel.spokes.*whole number"):
        asm.solve()


def test_reading_an_unrelated_derived_value_of_the_same_part_is_not_a_cycle(proj):
    asm = asm_of(proj)
    asm.rule("wheel.hub_len = wheel.wall", confirmed=True)   # wall = (tyre_d - bore_d) / 2
    asm.solve()
    assert asm.instances["wheel"].P["hub_len"] == pytest.approx(19.0)


def test_derived_value_that_reads_the_target_is_a_cycle(proj):
    asm = asm_of(proj)
    asm.rule("wheel.bore_d = wheel.wall - 10", confirmed=True)
    with pytest.raises(R.RuleError, match="cycle"):
        asm.solve()


def test_docstring_example_matches_the_fixture_rule_file():
    fixture = R.load_rule_file(R.SKILL_ROOT / "tests" / "fixtures" / "hinge_box" / "rules"
                               / "lid-fit.rules")
    doc = [ln.strip() for ln in R.__doc__.splitlines()]
    example = [ln.split(":", 1)[1].split("#")[0].strip() for ln in doc if ln.startswith("rule:")]
    assert example == [r.text for r in fixture.rules]
    assert f"purpose: {fixture.purpose}" in doc
    assert f"kind: {fixture.kind}" in doc and f"roles: {', '.join(fixture.roles)}" in doc


def test_user_rules_in_models_and_the_library_are_git_ignored():
    import subprocess
    root = R.SKILL_ROOT

    def ignored(rel):
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=root)
        return r.returncode == 0
    assert ignored("models/rules/my-robot-arm.rules")
    assert ignored("library/rules/anything.rules")
