"""把"安全默认值"变成可执行断言。

ARCHITECTURE.md 里写了几条硬约束: BYPASS 仅限 dev 且生产绝不打开、密钥不进仓库、
运行时 Wiki 不进版本管理。文档会过期, 断言不会 —— 谁改成 bypass 谁 CI 变红。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

ENV_EXAMPLE = REPO_ROOT / ".env.example"
GITIGNORE = REPO_ROOT / ".gitignore"

COMPOSE_FILES = sorted(REPO_ROOT.glob("docker-compose*.yml"))

# 看起来像真 key 的形态; .env.example 里只允许空值或占位符
_SECRET_LIKE = re.compile(r"^(?:sk-[A-Za-z0-9_\-]{16,}|[A-Fa-f0-9]{32,})$")


def _read(path: Path) -> str:
    # utf-8-sig 容忍编辑器写入的 BOM；errors=replace 避免队友用 GBK 追加一行就
    # 把整个测试炸成 UnicodeDecodeError（这里断言的都是 ASCII 片段，不影响结论）。
    return path.read_text(encoding="utf-8-sig", errors="replace")


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.exists(), "缺少 .env.example, 新人无法知道要配哪些变量"


def test_env_example_does_not_default_to_bypass() -> None:
    """默认值必须是 normal; BYPASS 一旦成为默认, 部署即越权。"""
    text = _read(ENV_EXAMPLE)
    match = re.search(r"^PERMISSION_MODE\s*=\s*(\S+)\s*$", text, re.MULTILINE)

    assert match is not None, ".env.example 应显式给出 PERMISSION_MODE 默认值"
    assert match.group(1).lower() != "bypass"


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda p: p.name)
def test_compose_never_enables_bypass(compose: Path) -> None:
    assert "bypass" not in _read(compose).lower(), f"{compose.name} 不应出现 bypass 模式"


def test_env_example_contains_no_real_looking_secret() -> None:
    """.env.example 是可以公开的; 任何一行形似真 key 都算泄漏。"""
    offenders = []
    for lineno, line in enumerate(_read(ENV_EXAMPLE).splitlines(), start=1):
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if "KEY" not in key.upper() and "TOKEN" not in key.upper():
            continue
        value = value.strip().strip('"').strip("'")
        if _SECRET_LIKE.match(value):
            offenders.append(f"{lineno}:{key.strip()}")

    assert offenders == [], f"疑似真实密钥被写进 .env.example: {offenders}"


@pytest.mark.parametrize("pattern", [".env", ".env.*"])
def test_gitignore_protects_local_secrets(pattern: str) -> None:
    lines = {line.strip() for line in _read(GITIGNORE).splitlines()}
    assert pattern in lines, f".gitignore 必须忽略 {pattern}"


def test_gitignore_excludes_runtime_wiki() -> None:
    """LLM Wiki 里可能含真实事件信息, 只能提交 CONVENTIONS.md。"""
    text = _read(GITIGNORE)
    assert "data/wiki/*" in text
    assert "!data/wiki/CONVENTIONS.md" in text
