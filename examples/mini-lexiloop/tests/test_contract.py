import subprocess
import sys
from pathlib import Path

import mini_lexiloop


def test_mini_lexiloop_module_and_public_exports():
    assert mini_lexiloop.LexiLoop is not None
    assert mini_lexiloop.FakeModelClient is not None
    assert not hasattr(mini_lexiloop, "MiniAgent")
    result = subprocess.run([sys.executable, "-m", "mini_lexiloop", "--help"], capture_output=True, text=True, check=True)
    assert "Teaching-sized LexiLoop agent harness" in result.stdout


def test_readme_main_mapping_points_to_existing_files():
    repo_root = Path(__file__).resolve().parents[3]
    main_files = [
        "lexiloop/cli.py",
        "lexiloop/runtime.py",
        "lexiloop/agent_loop.py",
        "lexiloop/context_manager.py",
        "lexiloop/providers/clients.py",
        "lexiloop/tool_executor.py",
        "lexiloop/tools.py",
        "lexiloop/task_state.py",
        "lexiloop/run_store.py",
        "lexiloop/workspace.py",
    ]
    for path in main_files:
        assert (repo_root / path).exists()
