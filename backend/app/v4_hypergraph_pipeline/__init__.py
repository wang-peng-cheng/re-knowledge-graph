from __future__ import annotations

"""v4.0 超图抽取流水线包。

该包独立于 `v2_pipeline` 与 `v3_temporal_pipeline`，用于研究突破二元关系
限制的高阶事件拓扑建模：

- `HypergraphExtractionEngine` 负责局部超边抽取与全局超图聚合。
- `HyperEdgeResult` 表达以事件为中心的星型/辐射式超边。
- `HypergraphExtractionResult` 额外输出可直接映射为关联矩阵的数据表示。
"""

from .parallel_engine import (
    HyperEdgeParticipant,
    HyperEdgeResult,
    HypergraphExtractionEngine,
    HypergraphExtractionResult,
    PartialHypergraphResult,
)

__all__ = [
    "HyperEdgeParticipant",
    "HyperEdgeResult",
    "HypergraphExtractionEngine",
    "HypergraphExtractionResult",
    "PartialHypergraphResult",
]
