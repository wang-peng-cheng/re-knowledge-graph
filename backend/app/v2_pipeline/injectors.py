from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domain.models import CleanedTextChunk

logger = logging.getLogger(__name__)

PROPER_NOUN_PATTERN = re.compile(r"\b(?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)*\b")
BOOK_TITLE_PATTERN = re.compile(r"《([^》\n]+)》")
DOUBLE_QUOTE_PATTERN = re.compile(r'"([^"\n]+)"')
SINGLE_QUOTE_PATTERN = re.compile(r"'([^'\n]+)'")


@dataclass(slots=True)
class InjectedChunk:
    """封装注入结构化先验后的文本块载体。

    v2.0 设计中，过滤层与抽取层之间不直接共享“裸文本”，而是通过本
    结构显式保留：

    - 原始清洗文本块对象。
    - 注入后的提示文本。
    - 未来依存句法解析、命名实体提示、篇章线索等结构化元数据。

    这样可以避免后续模块重复解析原始文本，也便于审计注入策略带来的
    效果变化。
    """

    original_chunk: CleanedTextChunk
    injected_text: str
    hints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class SyntaxInjector:
    """句法先验注入器骨架。

    当前版本只定义接口与数据流，不接入真实的 spaCy、HanLP 或其他句
    法分析器。它的职责是将原始 Chunk 包装为“更适合下游抽取器消费”
    的上下文输入，而不是直接执行关系抽取。

    未来典型增强点包括：

    - 基于依存句法树识别主谓宾、定中、并列与时间修饰结构。
    - 生成实体候选、事件触发词、时间锚点等结构化提示。
    - 为跨句关系抽取提供局部篇章图或指代消解线索。
    """

    def __init__(
        self,
        enable_dependency_prompt: bool = True,
        enable_entity_hint: bool = True,
        prompt_prefix: str | None = None,
    ) -> None:
        """初始化句法注入器。

        Args:
            enable_dependency_prompt: 是否在注入文本中加入句法结构提示。
            enable_entity_hint: 是否注入轻量实体提示位。
            prompt_prefix: 可选的领域前缀提示，用于未来按任务类型做定制。
        """

        self.enable_dependency_prompt = enable_dependency_prompt
        self.enable_entity_hint = enable_entity_hint
        self.prompt_prefix = prompt_prefix or "以下为已清洗文本，请结合结构化先验执行关系抽取："

    def batch_inject(self, chunks: Sequence[CleanedTextChunk]) -> list[InjectedChunk]:
        """批量对文本块执行结构化先验注入。"""

        return [self.inject(chunk) for chunk in chunks]

    def inject(self, chunk: CleanedTextChunk) -> InjectedChunk:
        """为单个文本块构造注入后的提示载体。

        注意：
        - 当前实现是完全安全的占位版本，不调用外部 NLP 模型。
        - 该方法保留清晰的扩展插槽，未来可无缝加入真实句法分析逻辑。
        """

        hints = self.build_hints(chunk)
        injected_text = self.render_injected_text(chunk=chunk, hints=hints)

        logger.debug("SyntaxInjector injected chunk=%s", chunk.chunk_id)

        return InjectedChunk(
            original_chunk=chunk,
            injected_text=injected_text,
            hints=hints,
            metadata={
                "injector": self.__class__.__name__,
                "dependency_prompt_enabled": self.enable_dependency_prompt,
                "entity_hint_enabled": self.enable_entity_hint,
            },
        )

    def build_hints(self, chunk: CleanedTextChunk) -> dict[str, Any]:
        """构造未来可供抽取器消费的结构化先验提示。

        当前不依赖真实依存句法树，而是给出稳定的数据契约：

        - `syntactic_focus`: 未来可填充主谓宾、时间状语、并列结构等。
        - `entity_candidates`: 未来可由 NER 或词法规则产生候选实体。
        - `time_hints`: 直接复用清洗层检测出的时间表达，减少信息丢失。
        """

        hints: dict[str, Any] = {
            "syntactic_focus": [],
            "entity_candidates": [],
            "time_hints": list(chunk.detected_time_expressions),
            "document_id": chunk.document_id,
            "chunk_id": chunk.chunk_id,
            "sequence_no": chunk.sequence_no,
        }

        if self.enable_dependency_prompt:
            hints["syntactic_focus"].append(
                "未来可在此注入依存句法树摘要，例如主语、谓语、宾语、时间修饰语和并列结构。"
            )

        if self.enable_entity_hint:
            candidates: list[str] = []
            text = chunk.cleaned_text

            for match in PROPER_NOUN_PATTERN.finditer(text):
                candidate = match.group(0).strip()
                if candidate:
                    candidates.append(candidate)

            for pattern in (BOOK_TITLE_PATTERN, DOUBLE_QUOTE_PATTERN, SINGLE_QUOTE_PATTERN):
                for match in pattern.finditer(text):
                    candidate = match.group(1).strip()
                    if candidate:
                        candidates.append(candidate)

            deduplicated_candidates = list(dict.fromkeys(candidates))
            hints["entity_candidates"].extend(deduplicated_candidates)

        return hints

    def render_injected_text(self, *, chunk: CleanedTextChunk, hints: dict[str, Any]) -> str:
        """将结构化先验渲染为下游抽取器可消费的文本。

        这里采用“显式结构段 + 原文正文”的形式，目的是让未来接入真实
        LLM 时可以直接把该字符串送入提示模板，而无需修改上游接口。
        """

        sections: list[str] = [self.prompt_prefix]

        if self.enable_dependency_prompt:
            sections.append("【句法先验提示】")
            sections.append("- 未来接入依存句法树后，将在此提供句法骨架摘要。")

        if self.enable_entity_hint:
            sections.append("【实体先验提示】")
            if hints.get("entity_candidates"):
                sections.append(
                    f"- 检测到高价值候选实体：{hints['entity_candidates']}，请在抽取时重点关注。"
                )
            else:
                sections.append("- 当前未检测到高价值候选实体。")

        if hints.get("time_hints"):
            sections.append("【时间提示】")
            sections.append(f"- 已检测时间表达: {hints['time_hints']}")

        sections.append("【正文】")
        sections.append(chunk.cleaned_text)

        return "\n".join(sections)
