"""Hybrid 检索的 RRF 融合: 排序语义 + 降级路径。

为什么 RRF 而不是加权分数: BM25 分数无上界, cosine 在 [-1,1], 量纲不同;
RRF 只用排名(1/(k+rank)), 对量纲不敏感, 且天然支持"两路都命中"的加成。
这些性质要能被测试固定住, 否则调参时很容易悄悄改成加权分数。
"""

from __future__ import annotations

import pytest

import app.core.hybrid_retriever as hybrid
from app.core.hybrid_retriever import hybrid_search
from tests._helpers import make_doc, patched


class _FakeIndex:
    """替代进程内 BM25 单例, 让融合逻辑可以脱离 Milvus / rank_bm25 测试。"""

    def __init__(self, results=None, ready: bool = True) -> None:
        self._results = list(results or [])
        self.is_ready = ready

    def search(self, query: str, k: int):
        return self._results[:k]


def _run(vector_docs, bm25_results, *, k, ready=True, **kwargs):
    with patched(hybrid, _bm25_index=_FakeIndex(bm25_results, ready=ready)):
        return hybrid_search("redis 内存 98%", vector_docs, k=k, **kwargs)


def test_falls_back_to_vector_when_bm25_not_ready() -> None:
    """BM25 索引没建好时不能报错, 直接给纯向量结果。"""
    docs = [make_doc("a"), make_doc("b"), make_doc("c")]
    result = _run(docs, [], k=2, ready=False)

    assert result == docs[:2]


def test_falls_back_to_vector_when_bm25_returns_empty() -> None:
    docs = [make_doc("a"), make_doc("b")]
    result = _run(docs, [], k=2)

    assert result == docs[:2]


def test_same_document_from_both_channels_is_deduplicated() -> None:
    """同一 chunk 两路都召回时只能出现一次(否则上下文被同一段话占满)。"""
    doc = make_doc("redis maxmemory 未设置")
    result = _run([doc], [(doc, 12.0)], k=5)

    assert result == [doc]


def test_rrf_prefers_document_hit_by_both_channels() -> None:
    shared = make_doc("redis 内存 98%")
    only_bm25 = make_doc("redis 内存告警规则")

    result = _run([shared], [(shared, 20.0), (only_bm25, 19.0)], k=2, bm25_weight=0.5)

    assert result[0] is shared


def test_bm25_weight_one_puts_bm25_rank_first() -> None:
    a = make_doc("a")
    b = make_doc("b")

    result = _run([a, b], [(b, 9.0), (a, 1.0)], k=2, bm25_weight=1.0)

    assert result == [b, a]


def test_bm25_weight_zero_puts_vector_rank_first() -> None:
    a = make_doc("a")
    b = make_doc("b")

    result = _run([a, b], [(b, 9.0), (a, 1.0)], k=2, bm25_weight=0.0)

    assert result == [a, b]


def test_bm25_only_document_can_enter_result() -> None:
    """纯向量会漏掉精确 token 命中的文档, 这正是加 BM25 的意义。"""
    vector_only = make_doc("redis 连接池建议")
    exact_hit = make_doc("ERR_CONN_REFUSED 排查")

    result = _run([vector_only], [(exact_hit, 30.0)], k=2, bm25_weight=0.9)

    assert exact_hit in result


def test_result_is_truncated_to_k() -> None:
    docs = [make_doc(f"d{i}") for i in range(5)]
    result = _run(docs, [(docs[4], 9.0)], k=2)

    assert len(result) == 2


@pytest.mark.parametrize("k", [1, 3])
def test_never_returns_more_than_k(k: int) -> None:
    docs = [make_doc(f"d{i}") for i in range(6)]
    bm25 = [(docs[i], float(6 - i)) for i in range(6)]

    assert len(_run(docs, bm25, k=k)) <= k


def test_same_content_different_source_is_kept_separate() -> None:
    """不同来源的同文本文档是两条证据, 不能按正文去重掉。"""
    text = "redis 内存使用率 98%"
    a = make_doc(text, source="sop/redis.md")
    b = make_doc(text, source="alert/redis-memory.md")

    result = _run([a], [(b, 10.0)], k=5)

    assert len(result) == 2
