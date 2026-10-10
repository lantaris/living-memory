"""Regression suite: the prototype's own scenario scripts, run against the engine.

The scripts under ``prototype/`` are the original plain-assert checks from the
memory prototype (see ``experements/memory-prototype/``). They import the engine
modules from ``python/`` via PYTHONPATH, so they exercise the live engine without
their own copies. ``test_retention.py`` is excluded: it needs a real LLM and is
run manually (``python tests/python/prototype/test_retention.py --run 1``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROTO = Path(__file__).resolve().parent / "prototype"

CASES = [
    ("test_scenario.py", []),
    ("test_session.py", ["--provider", "mock"]),
    ("test_loss_conflict.py", ["--provider", "mock"]),
    ("test_model_swap.py", ["--modes", "A"]),
    ("test_normalization.py", ["--tests", "unit"]),
    ("test_multi_session.py", []),
]


@pytest.mark.parametrize("script,args", CASES, ids=[case[0] for case in CASES])
def test_prototype_suite(script: str, args: list[str]) -> None:
    sandbox = PROTO / "sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "python") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    env.pop("MEMORY_LLM_PROVIDER", None)
    proc = subprocess.run(
        [sys.executable, str(PROTO / script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(PROTO),
        timeout=600,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"{script} exited {proc.returncode}\n{output}"
    assert "провалено" not in output, f"{script} reported failures\n{output}"
    assert "пройдены" in output, f"{script} did not report a verdict\n{output}"
