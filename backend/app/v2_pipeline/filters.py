from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domain.models import CleanedTextChunk

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FilterDecision:
    """封装单个文本块的过滤决策结果。

    该数据结构位于 v2.0 pipeline 的过滤层与后续注入层之间，负责显式
    记录每个 Chunk 是否被保留、保留理由以及中间启发式分数，便于后续：

    1. 审计为什么某个文本块被剔除。
    2. 在线上灰度阶段回放过滤效果。
    3. 在未来引入 Embedding 相似度模型后平滑替换打分逻辑。
    """

    chunk: CleanedTextChunk
    keep: bool
    score: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class HeuristicFilter:
    """v2.0 长文本跨文档图谱抽取中的启发式过滤器骨架。

    设计目标：

    - 在真正接入 Embedding 检索或语义相似度模型之前，先提供一个安
      全、可解释、零外部依赖的前置过滤层。
    - 通过轻量规则尽早剔除无效 Chunk，降低后续注入、并发抽取与聚
      合阶段的资源消耗。
    - 保持过滤器职责单一，只负责“是否值得进入 v2 抽取链路”的判定，
      不介入实体或关系推断。

    未来演进方向：

    - 基于 Embedding 相似度与主题召回分数判断 Chunk 是否与当前任务
      域强相关。
    - 融合交叉编码器重排结果，对低信息密度片段进行更细粒度裁剪。
    - 结合文档级上下文与历史图谱状态执行“图谱增量价值评估”。
    """

    _WHITESPACE_PATTERN = re.compile(r"\s+")

    def __init__(
        self,
        min_text_length: int = 40,
        min_alpha_numeric_ratio: float = 0.2,
        max_digit_ratio: float = 0.6,
        reserved_keywords: Sequence[str] | None = None,
    ) -> None:
        """初始化启发式过滤器。

        Args:
            min_text_length: 判定为“足够可抽取”的最小文本长度阈值。
            min_alpha_numeric_ratio: 文本中有效字符占比的最低阈值，用于
                粗略剔除大量符号、乱码或模板噪声。
            max_digit_ratio: 数字字符占比上限。过高通常意味着表格残片、
                编号列表或元数据块，不适合作为 RE 输入。
            reserved_keywords: 白名单关键词。若文本命中关键词，可放宽部
                分启发式限制，避免误杀关键情报片段。
        """

        self.min_text_length = min_text_length
        self.min_alpha_numeric_ratio = min_alpha_numeric_ratio
        self.max_digit_ratio = max_digit_ratio
        self.reserved_keywords = tuple(reserved_keywords or ())

    def filter_chunks(self, chunks: Sequence[CleanedTextChunk]) -> list[FilterDecision]:
        """批量评估文本块并返回显式决策结果。

        返回 `FilterDecision` 而非直接返回被保留的 Chunk，原因是企业级
        流水线通常需要保留被剔除样本的理由，用于审计、实验对照和观测。
        """

        return [self.evaluate_chunk(chunk) for chunk in chunks]

    def keep_chunks(self, chunks: Sequence[CleanedTextChunk]) -> list[CleanedTextChunk]:
        """返回通过过滤的文本块列表。"""

        return [decision.chunk for decision in self.filter_chunks(chunks) if decision.keep]

    def evaluate_chunk(self, chunk: CleanedTextChunk) -> FilterDecision:
        """评估单个文本块是否应进入后续 v2 抽取流程。"""

        normalized_text = self._normalize_text(chunk.cleaned_text)
        text_length = len(normalized_text)

        if not normalized_text:
            return FilterDecision(
                chunk=chunk,
                keep=False,
                score=0.0,
                reason="文本块为空或仅包含空白字符",
                metadata={"text_length": 0},
            )

        alpha_numeric_ratio = self._compute_alpha_numeric_ratio(normalized_text)
        digit_ratio = self._compute_digit_ratio(normalized_text)
        keyword_hit = self._has_reserved_keyword(normalized_text)

        passes_length = text_length >= self.min_text_length
        passes_density = alpha_numeric_ratio >= self.min_alpha_numeric_ratio
        passes_digit_ratio = digit_ratio <= self.max_digit_ratio

        # 该分数只作为骨架期的可观测指标，不代表最终语义价值分数。
        score = self._compute_heuristic_score(
            text_length=text_length,
            alpha_numeric_ratio=alpha_numeric_ratio,
            digit_ratio=digit_ratio,
            keyword_hit=keyword_hit,
        )

        keep = (passes_length and passes_density and passes_digit_ratio) or keyword_hit
        reason = self._build_reason(
            passes_length=passes_length,
            passes_density=passes_density,
            passes_digit_ratio=passes_digit_ratio,
            keyword_hit=keyword_hit,
        )

        logger.debug(
            "HeuristicFilter evaluated chunk=%s keep=%s score=%.3f",
            chunk.chunk_id,
            keep,
            score,
        )

        return FilterDecision(
            chunk=chunk,
            keep=keep,
            score=score,
            reason=reason,
            metadata={
                "text_length": text_length,
                "alpha_numeric_ratio": alpha_numeric_ratio,
                "digit_ratio": digit_ratio,
                "keyword_hit": keyword_hit,
            },
        )

    def _normalize_text(self, text: str) -> str:
        """执行轻量归一化，避免规则判断受连续空白干扰。"""

        return self._WHITESPACE_PATTERN.sub(" ", text).strip()

    def _compute_alpha_numeric_ratio(self, text: str) -> float:
        """计算字母、数字及中文字符在文本中的占比。"""

        valid_char_count = sum(1 for char in text if char.isalnum() or "\u4e00" <= char <= "\u9fff")
        return valid_char_count / len(text) if text else 0.0

    def _compute_digit_ratio(self, text: str) -> float:
        """计算数字字符占比，用于识别表格残片、编号串和噪声数据块。"""

        digit_count = sum(1 for char in text if char.isdigit())
        return digit_count / len(text) if text else 0.0

    def _has_reserved_keyword(self, text: str) -> bool:
        """检查文本是否命中白名单关键词。"""

        return any(keyword in text for keyword in self.reserved_keywords)

    def _compute_heuristic_score(
        self,
        *,
        text_length: int,
        alpha_numeric_ratio: float,
        digit_ratio: float,
        keyword_hit: bool,
    ) -> float:
        """生成骨架期的启发式分数。

        未来接入 Embedding 后，该方法可替换为“规则分 + 语义分”的融合打
        分器，而不会影响对外接口。
        """

        normalized_length_score = min(text_length / max(self.min_text_length, 1), 2.0) / 2.0
        density_score = min(max(alpha_numeric_ratio, 0.0), 1.0)
        digit_penalty = 1.0 - min(max(digit_ratio, 0.0), 1.0)
        keyword_bonus = 0.1 if keyword_hit else 0.0

        return max(
            0.0,
            min(1.0, (normalized_length_score * 0.4) + (density_score * 0.4) + (digit_penalty * 0.2) + keyword_bonus),
        )

    def _build_reason(
        self,
        *,
        passes_length: bool,
        passes_density: bool,
        passes_digit_ratio: bool,
        keyword_hit: bool,
    ) -> str:
        """构造便于审计的文本化原因说明。"""

        if keyword_hit:
            return "命中白名单关键词，允许进入后续抽取流程"

        failed_checks: list[str] = []
        if not passes_length:
            failed_checks.append("文本长度不足")
        if not passes_density:
            failed_checks.append("有效字符密度过低")
        if not passes_digit_ratio:
            failed_checks.append("数字占比过高")

        if failed_checks:
            return "；".join(failed_checks)

        return "通过启发式预过滤"


class SemanticTriggerFilter:
    """基于目标 Schema 触发词的轻量语义过滤器。

    该过滤器不依赖额外 NLP 模型，而是使用静态触发词典为不同关系或实体
    类型提供“是否值得进入抽取阶段”的语义先验判断。
    """

    _DEFAULT_TRIGGER_LEXICON: dict[str, tuple[str, ...]] = {
        "conflict": ("战役", "冲突", "逮捕", "battle", "war", "conflict", "attack"),
        "organization": ("公司", "集团", "机构", "organization", "company", "group", "inc", "ltd"),
        "person": ("人物", "人员", "先生", "女士", "person", "mr", "ms", "president", "leader"),
        "event": ("事件", "会议", "发布", "event", "summit", "meeting", "launch"),
        "location": ("城市", "地点", "地区", "location", "city", "province", "country"),
    }

    def __init__(self, target_schemas: list[str] | None = None) -> None:
        """初始化语义触发过滤器。

        Args:
            target_schemas: 目标关系或实体类型列表，例如 `["conflict", "person"]`。
        """

        self.target_schemas = [schema.strip().lower() for schema in (target_schemas or []) if schema.strip()]
        self.trigger_lexicon = self._DEFAULT_TRIGGER_LEXICON

    def evaluate_chunk(self, chunk: CleanedTextChunk) -> FilterDecision:
        """评估文本块是否命中目标 Schema 的语义触发词。"""

        normalized_text = chunk.cleaned_text.lower()
        if not self.target_schemas:
            return FilterDecision(
                chunk=chunk,
                keep=True,
                score=0.5,
                reason="未配置目标大纲，默认允许通过语义过滤",
                metadata={
                    "matched_schemas": [],
                    "matched_triggers": [],
                    "target_schemas": [],
                },
            )

        matched_schemas: list[str] = []
        matched_triggers: list[str] = []
        for schema in self.target_schemas:
            schema_triggers = self.trigger_lexicon.get(schema, ())
            for trigger in schema_triggers:
                if trigger.lower() in normalized_text:
                    matched_schemas.append(schema)
                    matched_triggers.append(trigger)

        deduplicated_schemas = list(dict.fromkeys(matched_schemas))
        deduplicated_triggers = list(dict.fromkeys(matched_triggers))

        if not deduplicated_triggers:
            return FilterDecision(
                chunk=chunk,
                keep=False,
                score=0.1,
                reason="未命中任何目标大纲 (Schema) 语义触发词",
                metadata={
                    "matched_schemas": [],
                    "matched_triggers": [],
                    "target_schemas": list(self.target_schemas),
                },
            )

        hit_count = len(deduplicated_triggers)
        score = min(1.0, 0.5 + min(hit_count, 5) * 0.1)
        return FilterDecision(
            chunk=chunk,
            keep=True,
            score=score,
            reason=f"命中目标大纲语义触发词: {deduplicated_triggers}",
            metadata={
                "matched_schemas": deduplicated_schemas,
                "matched_triggers": deduplicated_triggers,
                "target_schemas": list(self.target_schemas),
                "trigger_hit_count": hit_count,
            },
        )


class CascadeFilterPipeline:
    """级联语义过滤管线。

    Stage 1 使用启发式过滤器快速剔除明显无效的文本块。
    Stage 2 使用目标 Schema 触发器做轻量语义校验。
    """

    def __init__(
        self,
        *,
        target_schemas: list[str] | None = None,
        heuristic_filter: HeuristicFilter | None = None,
        semantic_filter: SemanticTriggerFilter | None = None,
    ) -> None:
        """初始化级联过滤管线。"""

        self.heuristic_filter = heuristic_filter or HeuristicFilter()
        self.semantic_filter = semantic_filter or SemanticTriggerFilter(target_schemas=target_schemas)

    def filter_chunks(self, chunks: Sequence[CleanedTextChunk]) -> list[FilterDecision]:
        """按级联顺序执行过滤，并返回最终审计决策列表。"""

        decisions: list[FilterDecision] = []
        for chunk in chunks:
            stage1_decision = self.heuristic_filter.evaluate_chunk(chunk)
            if not stage1_decision.keep:
                decisions.append(
                    FilterDecision(
                        chunk=chunk,
                        keep=False,
                        score=stage1_decision.score,
                        reason=stage1_decision.reason,
                        metadata={
                            "cascade_stage": "stage1_heuristic_rejected",
                            "stage1": {
                                "keep": stage1_decision.keep,
                                "score": stage1_decision.score,
                                "reason": stage1_decision.reason,
                                "metadata": dict(stage1_decision.metadata),
                            },
                        },
                    )
                )
                continue

            stage2_decision = self.semantic_filter.evaluate_chunk(chunk)
            decisions.append(
                FilterDecision(
                    chunk=chunk,
                    keep=stage2_decision.keep,
                    score=stage2_decision.score,
                    reason=stage2_decision.reason,
                    metadata={
                        "cascade_stage": "stage2_semantic_evaluated",
                        "stage1": {
                            "keep": stage1_decision.keep,
                            "score": stage1_decision.score,
                            "reason": stage1_decision.reason,
                            "metadata": dict(stage1_decision.metadata),
                        },
                        "stage2": {
                            "keep": stage2_decision.keep,
                            "score": stage2_decision.score,
                            "reason": stage2_decision.reason,
                            "metadata": dict(stage2_decision.metadata),
                        },
                    },
                )
            )

        return decisions
