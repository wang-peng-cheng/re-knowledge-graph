from __future__ import annotations

"""v2.0 长文本跨文档知识图谱抽取流水线包。

该包提供面向应用层的 v2 抽取架构骨架，当前版本遵循领域驱动设计中
“明确边界、先定义契约、再逐步填充实现”的思路：

- `HeuristicFilter` 负责 Chunk 预过滤。
- `SyntaxInjector` 负责结构化先验注入。
- `MapReduceExtractionEngine` 负责主流程编排。

对外默认暴露核心编排类，便于后续在应用服务层或 API 层直接注入使用。
"""

from .filters import FilterDecision, HeuristicFilter
from .injectors import InjectedChunk, SyntaxInjector
from .parallel_engine import MapReduceExtractionEngine, PartialGraphResult

__all__ = [
    "FilterDecision",
    "HeuristicFilter",
    "InjectedChunk",
    "MapReduceExtractionEngine",
    "PartialGraphResult",
    "SyntaxInjector",
]
