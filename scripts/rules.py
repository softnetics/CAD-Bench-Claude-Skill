#!/usr/bin/env python3
"""rules.py -- a part's purpose, written down as rules the user confirmed.

One plain-text file per kind of part:

    kind: wheel hub
    purpose: A wheel pressed onto a motor shaft; carries the robot's weight.
    roles: wheel, shaft
    confirmed: 2026-10-18
    rule: wheel.bore_d = shaft.shaft_d + 0.1     # printed holes shrink: presses on
    rule: shaft.shaft_len >= wheel.hub_len       # the shaft reaches through the hub

`=` rules SET a parameter before anything is built, so a size change carries
through; `>=`, `<=`, `>`, `<`, `==` rules are CHECKED (a break warns, export
still happens). A file with no `confirmed:` line is ignored.

Scopes: project rules in `cad/rules/` (or `<assembly dir>/rules/` outside a
project), worldwide rules in `<skill>/library/rules/` -- git-ignored, because
the installed skill is a clone of a public repo. Project wins over worldwide.

    python scripts/rules.py list [ASSEMBLY.py | DIR]     # one line
"""
from __future__ import annotations

import ast
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


class RuleError(RuntimeError):
    """A rule that cannot be read or applied (unknown name, cycle, contradiction)."""


@dataclass
class Rule:
    text: str
    why: str = ""
    source: str = ""


@dataclass
class RuleFile:
    path: Path
    kind: str
    purpose: str
    roles: list
    confirmed: str | None
    rules: list


@dataclass
class RuleResult:
    rule: Rule
    ok: bool
    lhs: float
    rhs: float
    op: str            # "=" for a rule that set a value

    def describe(self):
        why = f" ({self.rule.why})" if self.rule.why else ""
        if self.op == "=":
            return f"{self.rule.text} -> {self.lhs:.4g}{why}"
        return f"{self.rule.text}: {self.lhs:.4g} vs {self.rhs:.4g}{why}"


# ------------------------------------------------------------------ files

def load_rule_file(path):
    path = Path(path)
    meta, rules = {}, []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "rule":
            text, _, why = value.partition("#")
            rules.append(Rule(text.strip(), why.strip(), path.name))
        else:
            meta[key] = value
    if "kind" not in meta:
        raise RuleError(f"{path.name}: no 'kind:' line")
    roles = [r.strip() for r in meta.get("roles", "").split(",") if r.strip()]
    return RuleFile(path, meta["kind"], meta.get("purpose", ""), roles,
                    meta.get("confirmed") or None, rules)


def project_rules_dir(asm_path):
    here = Path(asm_path).resolve().parent
    if here.name == "assemblies" and here.parent.name == "cad":
        return here.parent / "rules"
    return here / "rules"


def world_rules_dir():
    root = os.environ.get("CAD_BENCH_LIBRARY")
    return (Path(root) if root else SKILL_ROOT / "library") / "rules"


def _files(folder):
    folder = Path(folder)
    return sorted(folder.glob("*.rules")) if folder.is_dir() else []


def find_kind(kind, project_dir, world_dir):
    for folder in (project_dir, world_dir):
        for f in _files(folder):
            rf = load_rule_file(f)
            if rf.kind.casefold() == kind.casefold():
                return rf
    return None


# ------------------------------------------------------------------ expressions

_FUNCS = {"min": min, "max": max, "abs": abs, "sqrt": math.sqrt}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
        ast.Pow: lambda a, b: a ** b}
_CMP = {ast.GtE: (">=", lambda a, b: a >= b - 1e-9),
        ast.LtE: ("<=", lambda a, b: a <= b + 1e-9),
        ast.Gt: (">", lambda a, b: a > b), ast.Lt: ("<", lambda a, b: a < b),
        ast.Eq: ("==", lambda a, b: math.isclose(a, b, abs_tol=1e-6))}


def _parse(text):
    try:
        tree = ast.parse(text, mode="exec")
    except SyntaxError as e:
        raise RuleError(f"cannot read rule {text!r}: {e.msg}") from e
    if len(tree.body) != 1:
        raise RuleError(f"rule {text!r}: one statement per rule")
    return tree.body[0]


def _ref(node, text):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    raise RuleError(f"rule {text!r}: write names as instance.parameter")


def _refs(node, text):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            out.append(_ref(n, text))
    return out


def bind(text, roles):
    """Replace role names (wheel, shaft) with instance names (wheel_l, motor_l)."""
    stmt = _parse(text)
    for n in ast.walk(stmt):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if n.value.id not in roles:
                raise RuleError(f"rule {text!r}: role {n.value.id!r} is not bound "
                                f"(bound: {', '.join(roles) or 'none'})")
            n.value.id = roles[n.value.id]
    return ast.unparse(stmt)


def _eval(node, lookup, text):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Attribute):
        return lookup(*_ref(node, text))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left, lookup, text),
                                   _eval(node.right, lookup, text))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand, lookup, text)
        return -v if isinstance(node.op, ast.USub) else v
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS and not node.keywords):
        return float(_FUNCS[node.func.id](*(_eval(a, lookup, text) for a in node.args)))
    raise RuleError(f"rule {text!r}: only numbers, instance.parameter, + - * / **, "
                    f"and {', '.join(_FUNCS)} are allowed")


def _classify(rule):
    stmt = _parse(rule.text)
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            raise RuleError(f"rule {rule.text!r}: one target")
        return "set", _ref(stmt.targets[0], rule.text), stmt.value
    if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Compare)
            and len(stmt.value.ops) == 1 and type(stmt.value.ops[0]) in _CMP):
        return "check", None, stmt.value
    raise RuleError(f"rule {rule.text!r}: write 'a.x = ...' or 'a.x >= ...'")


def apply(rules, params, derive, given=None):
    """Apply `rules` to `params` ({instance: {param: value}}) in place.

    `derive(instance, P)` returns that instance's derived values. `given` is
    {instance: set of params given explicitly}; a rule may not also set one.
    Returns a list of RuleResult (sets first, then checks).
    """
    given = given or {}
    sets, checks = [], []
    for r in rules:
        kind, target, expr = _classify(r)
        (sets if kind == "set" else checks).append((r, target, expr))

    targets = {}
    for r, (inst, p), _ in sets:
        if inst not in params:
            raise RuleError(f"rule {r.text!r}: no instance {inst!r}")
        if p not in params[inst]:
            raise RuleError(f"rule {r.text!r}: {inst}.{p} is not a parameter")
        if p in given.get(inst, ()):
            raise RuleError(f"rule {r.text!r} sets {inst}.{p}, which add(params=...) "
                            f"also gives; keep one")
        if (inst, p) in targets:
            raise RuleError(f"{inst}.{p} is set by two rules")
        targets[(inst, p)] = r

    def deps(expr, text):
        out = set()
        for inst, name in _refs(expr, text):
            if inst not in params:
                raise RuleError(f"rule {text!r}: no instance {inst!r}")
            if name in params[inst]:
                if (inst, name) in targets:
                    out.add((inst, name))
            else:                       # a derived value: depends on every set of inst
                out |= {t for t in targets if t[0] == inst}
        return out

    graph = {tuple(t): deps(e, r.text) for r, t, e in sets}
    order, done, visiting = [], set(), []

    def visit(node):
        if node in done:
            return
        if node in visiting:
            loop = visiting[visiting.index(node):] + [node]
            raise RuleError("rule cycle: " + " -> ".join(f"{i}.{p}" for i, p in loop))
        visiting.append(node)
        for d in graph[node]:
            visit(d)
        visiting.pop()
        done.add(node)
        order.append(node)

    for node in graph:
        visit(node)

    def lookup(inst, name):
        if inst not in params:
            raise RuleError(f"no instance {inst!r} in a rule")
        if name in params[inst]:
            return float(params[inst][name])
        d = derive(inst, dict(params[inst]))
        if name not in d:
            raise RuleError(f"{inst}.{name}: neither a parameter nor a derived value")
        return float(d[name])

    results = []
    by_target = {tuple(t): (r, e) for r, t, e in sets}
    for inst, p in order:
        r, e = by_target[(inst, p)]
        v = _eval(e, lookup, r.text)
        params[inst][p] = v
        results.append(RuleResult(r, True, v, v, "="))
    for r, _, cmp in checks:
        a = _eval(cmp.left, lookup, r.text)
        b = _eval(cmp.comparators[0], lookup, r.text)
        sym, fn = _CMP[type(cmp.ops[0])]
        results.append(RuleResult(r, bool(fn(a, b)), a, b, sym))
    return results


# ------------------------------------------------------------------ assembly hook

def apply_assembly(asm):
    """Collect the assembly's confirmed rules, apply them to its instances' P."""
    rules, ignored = [], 0
    for text, why, confirmed, source in asm.rule_specs:
        if confirmed:
            rules.append(Rule(text, why, source))
        else:
            ignored += 1
    pdir, wdir = project_rules_dir(asm.path), world_rules_dir()
    for kind, roles in asm.rule_kinds:
        rf = find_kind(kind, pdir, wdir)
        if rf is None:
            raise RuleError(f"no rule file of kind {kind!r} in {pdir} or {wdir}")
        if not rf.confirmed:
            ignored += len(rf.rules)
            continue
        for r in rf.rules:
            rules.append(Rule(bind(r.text, roles), r.why, rf.path.name))
    if not rules:
        return [], ignored
    insts = asm.instances
    params = {n: i.P for n, i in insts.items()}
    given = {n: set(i.params) for n, i in insts.items()}
    results = apply(rules, params, lambda n, P: insts[n].model.derive(P), given)
    return results, ignored


# ------------------------------------------------------------------ CLI

def _describe(folder):
    names = []
    for f in _files(folder):
        try:
            rf = load_rule_file(f)
        except RuleError:
            names.append(f"{f.name} (unreadable)")
            continue
        names.append(rf.kind + ("" if rf.confirmed else " (unconfirmed)"))
    return ", ".join(names) or "none"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != "list" or len(argv) > 2:
        print("usage: rules.py list [ASSEMBLY.py | DIR]", file=sys.stderr)
        return 2
    where = Path(argv[1]) if len(argv) == 2 else Path.cwd() / "x.py"
    if where.is_dir():
        where = where / "x.py"
    print(f"rules: project: {_describe(project_rules_dir(where))}; "
          f"worldwide: {_describe(world_rules_dir())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
