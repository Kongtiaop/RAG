"""中文拆词单测（jieba 分词，不触 DB）。"""
from app.tools import extract_terms


def test_english_lowercased():
    assert extract_terms("HNSW Index") == ["hnsw", "index"]


def test_chinese_jieba_words_not_bigram():
    terms = extract_terms("向量索引的原理")
    assert "向量" in terms and "索引" in terms  # 真词，不是"量索"这种 bigram
    assert "量索" not in terms
    assert "的" not in terms  # 停用字剥离


def test_mixed_and_dedup():
    terms = extract_terms("MCP 协议与 MCP 传输")
    assert terms.count("mcp") == 1
    assert "协议" in terms


def test_stopword_only_query_empty():
    assert extract_terms("的了吗") == []
