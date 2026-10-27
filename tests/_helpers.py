"""测试公用小工具。

刻意不依赖 pytest 的 monkeypatch: 用显式 contextmanager 做"打补丁 + 还原",
好处是这些断言可以直接在裸 Python 里复跑一遍(方便离线排障)。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from langchain_core.documents import Document


@contextmanager
def patched(obj: Any, **attrs: Any) -> Iterator[None]:
    """临时替换对象属性, 退出时无条件还原(即使断言失败)。"""
    sentinel = object()
    old = {name: getattr(obj, name, sentinel) for name in attrs}
    for name, value in attrs.items():
        setattr(obj, name, value)
    try:
        yield
    finally:
        for name, value in old.items():
            if value is sentinel:
                delattr(obj, name)
            else:
                setattr(obj, name, value)


def make_doc(content: str, source: str = "sop/redis.md", chapter: str = "1") -> Document:
    """造一条检索结果文档, metadata 结构与 Milvus 回填结果保持一致。"""
    return Document(
        page_content=content,
        metadata={"source": source, "chapter": chapter, "parent_id": "", "parent_content": ""},
    )
