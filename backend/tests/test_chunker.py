"""chunker 单测：切块数量、heading 保留、代码块内 # 不误判。"""
from app.chunker import chunk_markdown

SAMPLE = """# 标题

开头介绍段落。

## 一、概念

这是第一节的内容，比较长一点，用来验证切块是否保留标题路径。

```python
# 这里的井号在代码块里，不应被当作标题
def f():
    pass
```

## 二、用法

第二节内容，较短。
"""


def test_chunk_count_and_headings():
    chunks = chunk_markdown("测试文档", SAMPLE)
    headings = [c.heading for c in chunks]
    # 小文档允许合并为 1 块，但所有标题必须保留（串接在 heading 里）
    assert len(chunks) >= 1
    joined = "；".join(headings)
    assert "一、概念" in joined and "二、用法" in joined


def test_code_block_hash_not_heading():
    chunks = chunk_markdown("测试文档", SAMPLE)
    all_text = "\n".join(c.content for c in chunks)
    assert "# 这里的井号在代码块里" in all_text
    # 代码块行没有被拆成独立小节
    assert not any(c.heading == "这里的井号在代码块里，不应被当作标题" for c in chunks)


def test_long_section_split():
    long_section = "## 长节\n\n" + "\n\n".join("段落" + "x" * 200 for _ in range(20))
    chunks = chunk_markdown("t", long_section)
    assert len(chunks) >= 2
    assert all(len(c.content) <= 1500 for c in chunks)
