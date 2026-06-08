from __future__ import annotations

"""v3.0 时态演化知识图谱抽取流水线包。

该包在物理上独立于 `v2_pipeline`，用于承载面向时间演化建模的实验性
抽取与聚合能力：

- `TemporalMapReduceEngine` 负责时态版本的 Map-Reduce 编排。
- `calculate_hawkes_confidence()` 提供 Hawkes 风格时间衰减计算。

V3 当前复用 V2 的过滤器与注入器契约，但核心聚合逻辑已在本包内独立实
现，不修改 V2 代码。
"""

from .parallel_engine import PartialGraphResult, TemporalMapReduceEngine, calculate_hawkes_confidence

__all__ = [
    "PartialGraphResult",
    "TemporalMapReduceEngine",
    "calculate_hawkes_confidence",
]
