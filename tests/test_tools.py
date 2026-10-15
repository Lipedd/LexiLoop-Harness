from pathlib import Path
import subprocess

from pico.tool_context import ToolContext
from pico.tools import build_tool_registry, tool_delegate, tool_read_file, tool_search


def build_context(tmp_path):
    return ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: (tmp_path / raw_path).resolve(),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=0,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
    )


def test_tool_context_supports_file_tools_without_full_pico(tmp_path):
    (tmp_path / "sample.txt").write_text("alpha\n", encoding="utf-8")
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: (tmp_path / raw_path).resolve(),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=0,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
    )

    result = tool_read_file(context, {"path": "sample.txt", "start": 1, "end": 1})

    assert "# sample.txt" in result
    assert "alpha" in result


def test_delegate_uses_context_spawn_without_runtime_import(tmp_path):
    calls = []
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: Path(tmp_path / raw_path),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=0,
        max_depth=1,
        spawn_delegate=lambda args: calls.append(args) or "delegate_result:\nDone",
    )

    result = tool_delegate(context, {"task": "inspect README.md", "max_steps": 2})

    assert result == "delegate_result:\nDone"
    assert calls == [{"task": "inspect README.md", "max_steps": 2}]


def test_build_tool_registry_binds_runners_to_tool_context(tmp_path):
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: Path(tmp_path / raw_path),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=1,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
    )

    tools = build_tool_registry(context)

    assert "read_file" in tools
    assert "delegate" not in tools


def test_search_decodes_rg_output_as_utf8_instead_of_host_locale(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    output = "pico/cli.py:344:处理 /help 命令\n".encode("utf-8")

    monkeypatch.setattr("pico.tools.shutil.which", lambda name: "rg.exe")

    def fake_run(command, **kwargs):
        assert kwargs["text"] is False
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

    monkeypatch.setattr("pico.tools.subprocess.run", fake_run)

    result = tool_search(context, {"pattern": "/help", "path": "."})

    assert result == "pico/cli.py:344:处理 /help 命令"


def test_search_treats_rg_exit_one_as_no_matches(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    monkeypatch.setattr("pico.tools.shutil.which", lambda name: "rg.exe")
    monkeypatch.setattr(
        "pico.tools.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b""),
    )

    result = tool_search(context, {"pattern": "missing", "path": "."})

    assert result == "(no matches)"


def test_search_falls_back_to_python_when_rg_cannot_start(tmp_path, monkeypatch):
    (tmp_path / "sample.txt").write_text("这里包含 /help 命令\n", encoding="utf-8")
    context = build_context(tmp_path)
    monkeypatch.setattr("pico.tools.shutil.which", lambda name: "rg.exe")

    def fail_to_start(command, **kwargs):
        raise OSError("rg failed to start")

    monkeypatch.setattr("pico.tools.subprocess.run", fail_to_start)

    result = tool_search(context, {"pattern": "/help", "path": "."})

    assert "sample.txt:1:这里包含 /help 命令" in result


def test_search_falls_back_to_python_when_rg_exits_with_error(tmp_path, monkeypatch):
    (tmp_path / "sample.txt").write_text("search target\n", encoding="utf-8")
    context = build_context(tmp_path)
    monkeypatch.setattr("pico.tools.shutil.which", lambda name: "rg.exe")
    monkeypatch.setattr(
        "pico.tools.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            2,
            stdout=b"",
            stderr=b"rg backend failed",
        ),
    )

    result = tool_search(context, {"pattern": "search target", "path": "."})

    assert "sample.txt:1:search target" in result
