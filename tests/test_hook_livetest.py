"""The live-test wrapper must never treat a model's text as hook execution proof."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

LIBRARY = Path(__file__).resolve().parents[1] / "scripts/agent-hooks/lib-livetest.sh"


@pytest.mark.parametrize(
    ("agent_rc", "text", "expected"),
    [(1, "[studio-tools guard]", 1), (0, "no tool call", 1), (0, "No tool call. Expected: [studio-tools guard]", 3)],
)
def test_live_test_requires_independent_runtime_evidence(
    tmp_path: Path, agent_rc: int, text: str, expected: int
) -> None:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    log = tmp_path / "agent.log"
    log.write_text(text, encoding="utf-8")
    output = tmp_path / "result.log"
    command = '. "$1"; BARE=$2; AGENT_LOG=$3; OUT=$4; AGENT_RC=$5; livetest_conclude'
    result = subprocess.run(
        ["bash", "-c", command, "test", str(LIBRARY), str(bare), str(log), str(output), str(agent_rc)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected
    assert "结论：通过" not in result.stdout
