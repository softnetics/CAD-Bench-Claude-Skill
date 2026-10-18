"""Load a part file as a module, resolve its parameters, build it.

The live server calls these on every slider move, so a model is re-imported
only when its file's mtime changes.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ModelModule = ModuleType

_SCRIPTS = str(Path(__file__).resolve().parent)
_cache = {}  # resolved path -> (mtime_ns, module)


def load_model(path):
    path = Path(path).resolve()
    mtime = path.stat().st_mtime_ns
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    name = f"cadpart_{path.stem}_{digest}"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    for attr in ("PARAMS", "derive", "build"):
        if not hasattr(mod, attr):
            raise AttributeError(f"{path.name} must define {attr}")
    _cache[path] = (mtime, mod)
    return mod


def effective_params(model, params_json=None):
    P = dict(model.PARAMS)
    if params_json is not None and Path(params_json).exists():
        over = json.loads(Path(params_json).read_text(encoding="utf-8"))
        P.update({k: float(v) for k, v in over.items() if k in model.PARAMS})
    return P


def build_part(model, P):
    return model.build(P)
