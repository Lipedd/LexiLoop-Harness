"""命令行入口。

这个模块负责把“用户怎么启动 lexiloop”翻译成 runtime 能理解的对象：
解析参数、挑模型后端、构建工作区快照、恢复或新建 session，
最后进入 one-shot 或交互式循环。
"""

import argparse
import os
import shutil
import sys
import textwrap

from .config import load_project_env, provider_env
from .learning.prompt import LearningPrompt
from .learning.service import TranslationLearningService
from .learning.store import LearningStore
from .providers.clients import AnthropicCompatibleModelClient, OllamaModelClient, OpenAICompatibleModelClient
from .runtime import LexiLoop, SessionStore
from .workspace import WorkspaceContext, middle

DEFAULT_SECRET_ENV_NAMES = (
    "LEXILOOP_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_TOKEN",
    "LEXILOOP_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "LEXILOOP_DEEPSEEK_API_KEY",
    "DEEPSEEK_API_KEY",
    "LEXILOOP_RIGHT_CODES_API_KEY",
    "RIGHT_CODES_API_KEY",
    "GITHUB_PAT",
    "GH_PAT",
)

# LexiLoop 的终端形象是一只小型“代码探测器”：顶部信标代表感知工作区，
# 正面的双目代表读取与验证，底部支点代表在本地仓库里稳定工作。
# 每行由多个色块组成，避免退化成普通的黑白 ASCII 标志。
WELCOME_ART = (
    (("       ╭─", "cyan"), ("◆", "violet"), ("─╮", "cyan")),
    (("     ╭─╯", "cyan"), ("   ", "mint"), ("╰─╮", "cyan")),
    (("    ╭┴─────────┴╮", "cyan"),),
    (("    │  ", "cyan"), ("●", "amber"), ("     ", "mint"), ("●", "amber"), ("  │", "cyan")),
    (("    │     ", "cyan"), ("◆", "violet"), ("     │", "cyan")),
    (("    ╰─╮", "cyan"), ("     ", "mint"), ("╭─╯", "cyan")),
    (("      ╰─┬─┬─╯", "mint"),),
    (("      ", "cyan"), ("◇", "violet"), (" ╰─╯ ", "mint"), ("◇", "violet")),
)

ANSI_STYLES = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "cyan": "\x1b[38;5;81m",
    "mint": "\x1b[38;5;121m",
    "violet": "\x1b[38;5;177m",
    "amber": "\x1b[38;5;221m",
    "muted": "\x1b[38;5;245m",
}
HELP_DETAILS = textwrap.dedent(
    """\
    Commands:
    /help    Show this help message.
    /memory  Show the agent's distilled working memory.
    /session Show the path to the saved session file.
    /english Show the latest prompt translation and first five words.
    /word    Alias for /english.
    /stats   Show translation and word-frequency statistics.
    /reset   Clear the current session history and memory.
    /exit    Exit the agent.
    """
).strip()


DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_OPENAI_BASE_URL = "https://www.right.codes/codex/v1"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_ANTHROPIC_BASE_URL = "https://www.right.codes/claude/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_PROVIDER = "deepseek"
PROVIDER_CHOICES = ("ollama", "openai", "anthropic", "deepseek")
SECRET_ENV_NAMES_VAR = "LEXILOOP_SECRET_ENV_NAMES"


def _effective_provider(args):
    # Provider 选择优先级：
    # 1. 用户显式传入 --provider
    # 2. 项目 .env / shell 里的 LEXILOOP_PROVIDER
    # 3. 代码里的默认 provider
    provider = getattr(args, "provider", None) or provider_env(
        "LEXILOOP_PROVIDER", default=DEFAULT_PROVIDER
    )
    if provider not in PROVIDER_CHOICES:
        choices = ", ".join(PROVIDER_CHOICES)
        raise ValueError(f"unknown provider: {provider}. expected one of: {choices}")
    return provider


def _effective_model(args, provider):
    # 模型选择优先级：
    # 1. 用户显式传入 --model
    # 2. provider 对应的环境变量
    # 3. 代码里的默认值
    explicit_model = getattr(args, "model", None)
    if explicit_model:
        return explicit_model
    if provider == "openai":
        model = provider_env("LEXILOOP_OPENAI_MODEL", ("OPENAI_MODEL",))
        if model:
            return model
        return DEFAULT_OPENAI_MODEL
    if provider == "anthropic":
        model = provider_env("LEXILOOP_ANTHROPIC_MODEL", ("ANTHROPIC_MODEL",))
        if model:
            return model
        return DEFAULT_ANTHROPIC_MODEL
    if provider == "deepseek":
        model = provider_env("LEXILOOP_DEEPSEEK_MODEL", ("DEEPSEEK_MODEL",))
        if model:
            return model
        return DEFAULT_DEEPSEEK_MODEL
    return DEFAULT_OLLAMA_MODEL


def _configured_secret_names(args):
    configured_secret_names = set(DEFAULT_SECRET_ENV_NAMES)
    configured_secret_names.update(str(name).upper() for name in args.secret_env_names)
    extra_names = os.environ.get(SECRET_ENV_NAMES_VAR, "")
    if extra_names.strip():
        configured_secret_names.update(
            item.strip().upper()
            for item in extra_names.split(",")
            if item.strip()
        )
    return sorted(configured_secret_names)


def _build_model_client(args):
    provider = _effective_provider(args)
    # CLI 只负责把 provider 选择翻译成具体 client。
    # 真正的提示词格式、缓存支持、HTTP 协议差异，都封装在 models.py 里。
    if provider == "openai":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("LEXILOOP_OPENAI_API_BASE", ("OPENAI_API_BASE",), DEFAULT_OPENAI_BASE_URL)
        api_key = provider_env(
            "LEXILOOP_OPENAI_API_KEY",
            ("OPENAI_API_KEY", "LEXILOOP_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY", "LEXILOOP_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        )
        return OpenAICompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
        )
    if provider == "anthropic":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("LEXILOOP_ANTHROPIC_API_BASE", ("ANTHROPIC_API_BASE",), DEFAULT_ANTHROPIC_BASE_URL)
        api_key = provider_env(
            "LEXILOOP_ANTHROPIC_API_KEY",
            ("ANTHROPIC_API_KEY", "LEXILOOP_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY", "LEXILOOP_OPENAI_API_KEY", "OPENAI_API_KEY"),
        )
        return AnthropicCompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
        )
    if provider == "deepseek":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("LEXILOOP_DEEPSEEK_API_BASE", ("DEEPSEEK_API_BASE",), DEFAULT_DEEPSEEK_BASE_URL)
        api_key = provider_env("LEXILOOP_DEEPSEEK_API_KEY", ("DEEPSEEK_API_KEY",))
        return AnthropicCompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
            # LexiLoop currently uses text-encoded tool calls and does not replay
            # provider-native thinking blocks. Keep the default transport mode
            # deterministic until that protocol is implemented end to end.
            thinking={"type": "disabled"},
        )

    model = _effective_model(args, provider)
    host = getattr(args, "host", DEFAULT_OLLAMA_HOST)
    return OllamaModelClient(
        model=model,
        host=host,
        temperature=args.temperature,
        top_p=args.top_p,
        timeout=args.ollama_timeout,
    )


def _supports_color(stream=None):
    """Only emit ANSI escapes for an interactive terminal that allows color."""

    stream = stream or sys.stdout
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _configure_stdio_fallback():
    """Prevent legacy Windows encodings from crashing on terminal glyphs.

    Interactive modern terminals keep their normal Unicode output. Redirected
    streams using GBK or another narrower encoding replace only unsupported
    glyphs instead of terminating the whole CLI.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def _style(text, *styles, enabled):
    if not enabled or not text:
        return text
    prefix = "".join(ANSI_STYLES[style] for style in styles)
    return f"{prefix}{text}{ANSI_STYLES['reset']}"


def _plain_segments(segments):
    return "".join(text for text, _ in segments)


def _render_segments(segments, color):
    return "".join(_style(text, style, enabled=color) for text, style in segments)


def build_welcome(agent, model, host, *, color=None, terminal_width=None):
    """Build the compact terminal welcome screen, with a plain-text fallback."""

    del host  # Kept in the public signature for compatibility with existing callers.
    color = _supports_color() if color is None else bool(color)
    columns = terminal_width or shutil.get_terminal_size((88, 20)).columns
    width = max(36, min(columns, 100))
    art_plain = [_plain_segments(line) for line in WELCOME_ART]
    art_rendered = [_render_segments(line, color) for line in WELCOME_ART]
    art_width = max(len(line) for line in art_plain)

    def brand(limit):
        product_name = "LexiLoop"
        suffix = "  local coding agent"
        if limit < len(product_name) + len(suffix):
            suffix = ""
        plain = product_name + suffix
        shades = ("violet", "cyan", "mint", "amber")
        rendered_name = "".join(
            _style(char, shades[index % len(shades)], "bold", enabled=color)
            for index, char in enumerate(product_name)
        )
        return plain, rendered_name + _style(suffix, "muted", enabled=color)

    def detail(label, value, limit):
        label_width = 11
        value = middle(value, max(1, limit - label_width))
        plain = f"{label:<{label_width}}{value}"
        rendered = _style(f"{label:<{label_width}}", "muted", enabled=color) + _style(
            value, "bold", enabled=color
        )
        return plain, rendered

    def info_rows(limit):
        branch_summary = f"{agent.workspace.branch}  ·  approval {agent.approval_policy}"
        return [
            brand(limit),
            (
                "read · reason · build",
                _style("read", "cyan", enabled=color)
                + _style(" · ", "muted", enabled=color)
                + _style("reason", "mint", enabled=color)
                + _style(" · ", "muted", enabled=color)
                + _style("build", "violet", enabled=color),
            ),
            ("", ""),
            detail("workspace", agent.workspace.cwd, limit),
            detail("model", model, limit),
            detail("branch", branch_summary, limit),
            detail("session", agent.session["id"], limit),
        ]

    gap = 4
    output = []
    if width >= 72:
        info_width = width - art_width - gap
        rows = info_rows(info_width)
        row_count = max(len(art_plain), len(rows))
        for index in range(row_count):
            if index < len(art_plain):
                left = art_rendered[index] + " " * (art_width - len(art_plain[index]))
            else:
                left = " " * art_width
            right = rows[index][1] if index < len(rows) else ""
            output.append((left + " " * gap + right).rstrip())
    else:
        indent = " " * max(0, (width - art_width) // 2)
        output.extend(indent + line for line in art_rendered)
        output.append("")
        output.extend(rendered for _, rendered in info_rows(width))

    divider = "─" * width
    if width >= 62:
        footer = (
            _style("›", "violet", "bold", enabled=color)
            + " "
            + _style("/help", "cyan", "bold", enabled=color)
            + _style(" commands   ·   ", "muted", enabled=color)
            + _style("/memory", "mint", "bold", enabled=color)
            + _style(" context   ·   ", "muted", enabled=color)
            + _style("/exit", "amber", "bold", enabled=color)
            + _style(" leave", "muted", enabled=color)
        )
    else:
        footer = (
            _style("›", "violet", "bold", enabled=color)
            + " "
            + _style("/help", "cyan", "bold", enabled=color)
            + _style("  ·  ", "muted", enabled=color)
            + _style("/exit", "amber", "bold", enabled=color)
        )
    output.extend(
        [
            _style(divider, "muted", enabled=color),
            footer,
        ]
    )
    return "\n".join(output)


def build_agent(args):
    """根据 CLI 参数装配出一个可运行的 LexiLoop 实例。

    为什么存在：
    命令行参数只是字符串和开关，runtime 需要的是已经装配好的对象图：
    model client、workspace snapshot、session store、secret 配置等。
    这个函数负责把“启动参数”翻译成“agent 运行现场”。

    输入 / 输出：
    - 输入：`argparse` 解析后的 `args`
    - 输出：一个新的 `LexiLoop`，或一个从旧 session 恢复出来的 `LexiLoop`

    在 agent 链路里的位置：
    它是整个程序启动链路里最靠近 runtime 的装配点。`main()` 先调它，
    得到 agent 后，后面无论是 one-shot 还是 REPL 模式，都会落到 `ask()`。
    """
    # 这里是 CLI 到 runtime 的装配点：
    # 先采集工作区快照和加载项目级环境，再整理 secret 名单、模型后端和 session。
    workspace = WorkspaceContext.build(args.cwd)
    load_project_env(workspace.repo_root)
    configured_secret_names = _configured_secret_names(args)
    store = SessionStore(workspace.repo_root + "/.lexiloop/sessions")
    model = _build_model_client(args)
    session_id = args.resume
    if session_id == "latest":
        session_id = store.latest()
    if session_id:
        return LexiLoop.from_session(
            model_client=model,
            workspace=workspace,
            session_store=store,
            session_id=session_id,
            approval_policy=args.approval,
            max_steps=args.max_steps,
            max_new_tokens=args.max_new_tokens,
            secret_env_names=configured_secret_names,
        )
    return LexiLoop(
        model_client=model,
        workspace=workspace,
        session_store=store,
        approval_policy=args.approval,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        secret_env_names=configured_secret_names,
    )


def build_arg_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="LexiLoop: a local coding agent with an observable, recoverable harness.",
    )
    parser.add_argument("prompt", nargs="*", help="Optional one-shot prompt.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default=None,
        help="Model backend to use. Defaults to LEXILOOP_PROVIDER or deepseek.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override. Defaults to qwen3.5:4b for Ollama, LEXILOOP_OPENAI_MODEL for openai, LEXILOOP_ANTHROPIC_MODEL for anthropic, and LEXILOOP_DEEPSEEK_MODEL for deepseek when set.",
    )
    parser.add_argument("--host", default=DEFAULT_OLLAMA_HOST, help="Ollama server URL.")
    parser.add_argument("--base-url", default=None, help="Provider API base URL for deepseek, openai, or anthropic.")
    parser.add_argument("--ollama-timeout", type=int, default=300, help="Ollama request timeout in seconds.")
    parser.add_argument("--openai-timeout", type=int, default=300, help="OpenAI-compatible request timeout in seconds.")
    parser.add_argument("--resume", default=None, help="Session id to resume or 'latest'.")
    parser.add_argument("--approval", choices=("ask", "auto", "never"), default="ask", help="Approval policy for risky tools.")
    parser.add_argument(
        "--secret-env-name",
        dest="secret_env_names",
        action="append",
        default=[],
        help="Extra environment variable names to treat as secrets for trace/report redaction.",
    )
    parser.add_argument("--max-steps", type=int, default=6, help="Maximum tool/model iterations per request.")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="Maximum model output tokens per step.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature sent to Ollama.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Top-p sampling value sent to Ollama.")
    parser.add_argument(
        "--no-learning",
        action="store_true",
        help="Disable the interactive technical-English learning bar.",
    )
    return parser


def _learning_enabled(args) -> bool:
    if getattr(args, "no_learning", False):
        return False
    configured = os.environ.get("LEXILOOP_LEARNING", "1").strip().lower()
    return configured not in {"0", "false", "no", "off"}


def _build_learning_ui(args, agent):
    """Build the optional UI without making it a runtime dependency."""

    if not _learning_enabled(args):
        return None, None
    try:
        service = TranslationLearningService(
            model_client=_build_model_client(args),
            store=LearningStore(),
            session_id=agent.session.get("id"),
        )
        return service, LearningPrompt(service)
    except Exception as exc:
        print(f"English learning disabled: {exc}", file=sys.stderr)
        return None, None


def _handle_learning_command(user_input, service):
    """Return ``(handled, output)`` for commands owned by the learning layer."""

    command, *arguments = user_input.split()
    if command not in {"/english", "/word", "/stats"}:
        return False, ""
    if service is None:
        return True, "English learning is disabled. Start without --no-learning to enable it."
    try:
        if command == "/stats":
            if arguments:
                return True, "Usage: /stats"
            return True, service.stats_text()
        if arguments:
            return True, f"Usage: {command}"
        return True, service.panel_text()
    except Exception as exc:
        return True, f"English learning is temporarily unavailable: {exc}"


def main(argv=None):
    _configure_stdio_fallback()
    args = build_arg_parser().parse_args(argv)
    agent = build_agent(args)

    model = getattr(agent.model_client, "model", getattr(args, "model", DEFAULT_OLLAMA_MODEL))
    host = getattr(agent.model_client, "host", getattr(agent.model_client, "base_url", getattr(args, "host", DEFAULT_OLLAMA_HOST)))
    print(build_welcome(agent, model=model, host=host))

    if args.prompt:
        # one-shot 模式：只跑一次 ask，不进入 REPL 循环。
        prompt = " ".join(args.prompt).strip()
        if prompt:
            print()
            try:
                print(agent.ask(prompt))
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        return 0

    learning_service, learning_ui = _build_learning_ui(args, agent)

    while True:
        # 交互模式：每次读取一条用户输入，交给同一个 agent，
        # 因此 session history 和 working memory 会跨轮延续。
        try:
            if learning_ui is not None:
                user_input = learning_ui.read().strip()
            else:
                prompt_color = _supports_color()
                prompt = _style("lexi", "mint", "bold", enabled=prompt_color) + _style(
                    " ❯ ", "violet", "bold", enabled=prompt_color
                )
                user_input = input("\n" + prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            if learning_service is not None:
                learning_service.close()
            return 0

        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            if learning_service is not None:
                learning_service.close()
            return 0
        if user_input == "/help":
            print(HELP_DETAILS)
            continue
        if user_input == "/memory":
            print(agent.memory_text())
            continue
        if user_input == "/session":
            print(agent.session_path)
            continue
        if user_input == "/reset":
            agent.reset()
            print("session reset")
            continue
        handled, output = _handle_learning_command(user_input, learning_service)
        if handled:
            print(output)
            continue

        if learning_service is not None:
            try:
                # This sidecar request runs on its own model client and worker
                # thread. The user task enters Agent Loop immediately below.
                learning_service.submit(user_input)
            except Exception as exc:
                # The learning sidecar must never block the coding task.
                print(f"English learning disabled: {exc}", file=sys.stderr)
                learning_service.close()
                learning_service = None
                learning_ui = None

        print()
        try:
            print(agent.ask(user_input))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
