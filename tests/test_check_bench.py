"""check_bench.py on recipes with and without draw()."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHECK = REPO / "scripts" / "check_bench.py"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")

PAGE = """<title>t</title>
<script>
const PARTS = {
"no-draw":{
  label:"No draw", file:"cad/parts/no_draw.py",
  params:[{id:"w",fs:"W",u:"MM",g:"Main",label:"W",min:1,max:10,step:0.5,val:4}],
  derive(p){ return {half:p.w/2}; },
  cards:d=>[["Half",d.half.toFixed(2)]],
  checks(p,d){ return [[d.half>=0.5,"Half is enough",d.half.toFixed(2)+" mm"]]; }
}%s
};
</script>
"""

BROKEN = """,
"broken":{
  label:"Broken", file:"cad/parts/broken.py",
  params:[{id:"w",fs:"W",u:"MM",g:"Main",label:"W",min:1,max:10,step:0.5,val:4}],
  derive(p){ return {}; },
  cards:d=>[],
  checks(p,d){ return [[d.w>=1,"Reads the wrong object",String(d.w)]]; }
}"""


def run(tmp_path, extra=""):
    page = tmp_path / "page.html"
    page.write_text(PAGE % extra, encoding="utf-8")
    return subprocess.run([sys.executable, str(CHECK), str(page)], capture_output=True,
                          text=True, cwd=tmp_path)


def test_recipe_without_draw_passes(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK   no-draw" in r.stdout
    assert "1 part(s), 0 problem(s)" in r.stdout


def test_recipe_without_draw_still_checks_the_rest(tmp_path):
    r = run(tmp_path, BROKEN)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL broken" in r.stdout and "read undefined d.w" in r.stdout
    assert "OK   no-draw" in r.stdout
