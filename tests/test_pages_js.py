"""Runs the bench pages' JavaScript tests (tests/js/*.test.mjs) under node."""
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
@pytest.mark.parametrize("test_file", sorted(p.name for p in JS.glob("*.test.mjs")))
def test_page_js(test_file):
    r = subprocess.run(["node", "--test", str(JS / test_file)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
