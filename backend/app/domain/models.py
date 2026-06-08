from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


class SourceType(str, Enum):
    """定义系统支持的上游数据来源类型。

    该枚举用于约束数据接入层的输入模式，帮助后续解析服务在
    URL 抓取、纯文本导入、PDF 解析和 Word 解析之间选择不同
    的处理分支。它对应论文 E2E pipeline 中的“数据接入层”。
    """

    URL = "url"
    TXT = "txt"
    PDF = "pdf"
    DOCX = "docx"


class ProcessingStatus(str, Enum):
    """定义文档在端到端流水线中的处理状态。

    该状态枚举用于刻画一条舆情文档从接收到最终完成图谱推理的
    生命周期，便于任务调度、失败恢复、可观测性追踪以及论文实
    验中的阶段性统计分析。
    """

    RECEIVED = "received"
    PARSED = "parsed"
    CLEANED = "cleaned"
    EXTRACTED = "extracted"
    GRAPH_WRITTEN = "graph_written"
    REASONED = "reasoned"
    FAILED = "failed"


class AgentRole(str, Enum):
    """定义 Multi-Agent 关系抽取框架中的智能体角色。

    该枚举直接对应论文核心创新之一，即多智能体零样本关系抽取
    与自我降噪流程。不同角色在 pipeline 中承担规划、抽取、批
    判和裁决等职责，用于提升在噪声语料上的鲁棒性与可解释性。
    """

    PLANNER = "planner"
    EXTRACTOR = "extractor"
    CRITIC = "critic"
    JUDGE = "judge"


class DocumentIngestRequest(BaseModel):
    """定义数据接入层创建任务时使用的输入模型。

    该模型描述前端向后端提交的原始输入请求，是整个论文系统
    pipeline 的入口。请求可能来自网页 URL，也可能来自用户上
    传的 TXT、PDF、Word 文件。后续接入服务会依据该模型决定
    采用哪一种解析与入库分支。

    Attributes:
        source_type: 数据来源类型，用于区分 URL 抓取和文件解析。
        source_url: 当来源为 URL 时的原始网页地址。
        filename: 当来源为文件时的原始文件名，便于审计和溯源。
        media_type: 上传文件的 MIME 类型，用于辅助解析策略选择。
        content_bytes: 文件二进制内容，仅在非 URL 输入时使用。
        requested_by: 触发本次请求的用户标识、实验标签或审计标签。
    """

    source_type: SourceType = Field(description="数据来源类型，决定接入层后续采用何种解析路径。")
    source_url: Optional[HttpUrl] = Field(default=None, description="当来源为 URL 时，由前端传入的网页地址。")
    filename: Optional[str] = Field(default=None, description="当来源为文件时的原始文件名。")
    media_type: Optional[str] = Field(default=None, description="上传文件的 MIME 类型，例如 text/plain 或 application/pdf。")
    content_bytes: Optional[bytes] = Field(default=None, description="文件原始二进制内容，仅在文件上传模式下使用。")
    requested_by: Optional[str] = Field(default=None, description="请求发起者标识，可用于审计、实验分组与权限记录。")


class RawDocumentRecord(BaseModel):
    """定义原始文档在关系型数据库中的标准化存储结构。

    该模型位于“数据接入层”和“清洗与抽取层”之间，用于承接已
    解析完成但尚未进入清洗流程的原始文档。它是后续脏数据流式
    读取、文本清洗以及抽取任务重跑的重要数据基座。

    Attributes:
        document_id: 文档全局唯一标识，用于串联后续所有处理阶段。
        source_type: 文档来源类型，记录其接入方式。
        source_uri: 统一化后的来源地址，可为 URL、文件路径或对象存储定位符。
        raw_text: 初步解析后的原始文本内容，允许保留噪声。
        created_at: 原始记录写入系统的时间戳。
        metadata: 补充元数据，例如解析器版本、抓取头信息、上传人信息等。
    """

    document_id: str
    source_type: SourceType
    source_uri: str
    raw_text: str
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CleanedTextChunk(BaseModel):
    """定义清洗后可供关系抽取模块消费的文本切片。

    该模型是“清洗与抽取层”的核心中间表示。系统先对原始文档进
    行去噪、结构清洗与时间表达规整，再切分为可被大模型稳定处
    理的块级输入，以便后续 Multi-Agent RE 模块执行零样本抽取。

    Attributes:
        chunk_id: 文本块唯一标识。
        document_id: 所属文档标识，用于回溯到原始文档。
        sequence_no: 在同一文档中的顺序编号，便于恢复上下文。
        cleaned_text: 清洗后的文本内容。
        char_start: 在原始文档或清洗后全文中的起始偏移。
        char_end: 在原始文档或清洗后全文中的结束偏移。
        detected_time_expressions: 当前文本块中识别出的显式或隐式时间表达。
        metadata: 与该文本块相关的额外信息，例如分段标签、主题标签等。
    """

    chunk_id: str
    document_id: str
    sequence_no: int
    cleaned_text: str
    char_start: int
    char_end: int
    detected_time_expressions: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EntityMention(BaseModel):
    """定义实体抽取与规范化后的标准表示。

    该模型用于表达一个实体在文本中的提及及其规范化结果，是构建
    时序知识图谱节点的直接输入。实体抽取结果既服务于关系抽取，
    也服务于后续图谱聚合、别名归并和推理上下文构造。

    Attributes:
        entity_id: 实体唯一标识，可为规范化后的稳定 ID。
        surface_form: 实体在原文中的表层出现形式。
        canonical_name: 归一化后的标准实体名称。
        entity_type: 实体类型，例如人物、组织、地点、事件等。
        char_start: 实体在文本块中的起始字符偏移。
        char_end: 实体在文本块中的结束字符偏移。
        confidence: 当前实体识别与规范化结果的置信度。
    """

    entity_id: str
    surface_form: str
    canonical_name: str
    entity_type: str
    char_start: int
    char_end: int
    confidence: float


class TemporalRelation(BaseModel):
    """定义带有时间信息的关系实例。

    该模型是论文第二个核心创新点的重要数据载体。它不仅描述两个
    实体之间的关系类型，还显式记录观测时间、有效起止区间、证据
    文本以及多智能体投票信息，从而支持时序图谱构建与未来关系推
    演任务。

    Attributes:
        relation_id: 关系实例唯一标识。
        head_entity_id: 关系头实体标识。
        tail_entity_id: 关系尾实体标识。
        relation_type: 关系类型标签。
        confidence: 该关系实例的综合置信度。
        observed_at: 该关系被文本观测到的时间点。
        valid_from: 该关系被认为开始生效的时间。
        valid_to: 该关系被认为结束生效的时间。
        evidence_chunk_ids: 支撑该关系的文本块标识列表。
        evidence_texts: 支撑该关系的证据片段列表。
        agent_votes: 不同智能体对该关系给出的分数或投票结果。
        attributes: 关系附加属性，例如地点、事件标签、极性等。
    """

    relation_id: str
    head_entity_id: str
    tail_entity_id: str
    relation_type: str
    confidence: float
    observed_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    evidence_chunk_ids: List[str] = Field(default_factory=list)
    evidence_texts: List[str] = Field(default_factory=list)
    agent_votes: Dict[str, float] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class AgentDecision(BaseModel):
    """定义单个智能体在抽取链路中的中间决策结果。

    该模型用于完整保留 Planner、Extractor、Critic、Judge 等不
    同智能体的推断轨迹，支持后续实验分析、错误归因、提示词调优
    与论文中的可解释性展示。

    Attributes:
        agent_role: 当前决策对应的智能体角色。
        rationale: 当前智能体给出的文本化推理说明或裁决理由。
        accepted_relations: 被当前智能体接受的候选关系标识列表。
        rejected_relations: 被当前智能体否决的候选关系标识列表。
        metadata: 额外记录，例如提示模板版本、采样参数、轮次信息等。
    """

    agent_role: AgentRole
    rationale: str
    accepted_relations: List[str] = Field(default_factory=list)
    rejected_relations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """定义关系抽取阶段输出的统一结果模型。

    该模型汇总文档级或批次级文本块的实体抽取结果、时序关系结果与
    智能体轨迹信息，是写入图数据库之前最重要的结构化中间产物。

    Attributes:
        document_id: 本次抽取结果所属的文档标识。
        entities: 抽取得到的实体列表。
        relations: 抽取得到的时序关系列表。
        agent_trace: 多智能体流程中的关键决策轨迹。
        metadata: 抽取阶段的附加元数据，例如 Mermaid 图、裁决说明与运行统计。
        status: 当前抽取结果所对应的处理状态。
    """

    document_id: str
    entities: List[EntityMention] = Field(default_factory=list)
    relations: List[TemporalRelation] = Field(default_factory=list)
    agent_trace: List[AgentDecision] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    status: ProcessingStatus = ProcessingStatus.EXTRACTED


class GraphWriteRequest(BaseModel):
    """定义将抽取结果写入时态图数据库时使用的请求模型。

    该模型起到“抽取模块”和“图谱存储模块”之间的解耦作用。服务层
    可以先将 ExtractionResult 转换为该标准写入模型，再交由底层
    图数据库仓储完成实体、关系及时间属性的持久化。

    Attributes:
        document_id: 本次写入所属的文档标识。
        entities: 待写入图数据库的实体节点集合。
        relations: 待写入图数据库的时序关系集合。
        write_mode: 写入模式，例如 upsert、append 或 candidate_only。
    """

    document_id: str
    entities: List[EntityMention] = Field(default_factory=list)
    relations: List[TemporalRelation] = Field(default_factory=list)
    write_mode: str = Field(default="upsert", description="图写入模式，例如 upsert、append 或 candidate_only。")


class TemporalGraphSnapshot(BaseModel):
    """定义给定时间窗口下的图快照表示。

    该模型服务于前端时序演化展示与 TKG 推理模块。系统可以根据某
    个时间窗口、实体子集或事件主题，将时态图数据库中的子图投影
    为一个快照对象，以便前端渲染和大模型上下文构造。

    Attributes:
        snapshot_id: 图快照唯一标识。
        window_start: 快照起始时间边界。
        window_end: 快照结束时间边界。
        entities: 快照中包含的实体集合。
        relations: 快照中包含的关系集合。
        metadata: 快照级附加元数据，例如筛选条件、布局建议、统计信息等。
    """

    snapshot_id: str
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    entities: List[EntityMention] = Field(default_factory=list)
    relations: List[TemporalRelation] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReasoningRequest(BaseModel):
    """定义时序图谱推理模块的输入请求模型。

    该模型对应论文中的 TKG Extrapolation 任务，用于限定推理涉及
    的目标实体、候选关系类型、历史时间窗口与未来预测范围。前端
    的“推理”按钮可将用户选择的图上下文编码为该模型发送到后端。

    Attributes:
        target_entities: 需要重点推理的目标实体标识列表。
        relation_types: 需要关注的关系类型列表。
        window_start: 历史观测窗口的起始时间。
        window_end: 历史观测窗口的结束时间。
        horizon_end: 未来推演的截止时间。
        top_k: 返回的候选假设数量上限。
        include_graph_context: 是否在推理时显式携带图结构上下文。
    """

    target_entities: List[str] = Field(default_factory=list)
    relation_types: List[str] = Field(default_factory=list)
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    horizon_end: Optional[datetime] = None
    top_k: int = 10
    include_graph_context: bool = True


class ReasoningHypothesis(BaseModel):
    """定义单条未来关系推演假设。

    该模型用于承载推理模块生成的候选未来关系，包括预测出的关系
    本体、预测生效时间、解释文本以及支撑该推断的图路径信息。

    Attributes:
        hypothesis_id: 假设唯一标识。
        relation: 被预测的时序关系对象。
        forecast_time: 预测关系可能发生或生效的时间点。
        rationale: 大模型或混合推理模块给出的解释文本。
        supporting_paths: 支撑当前假设的图路径或模式标识。
    """

    hypothesis_id: str
    relation: TemporalRelation
    forecast_time: Optional[datetime] = None
    rationale: str
    supporting_paths: List[str] = Field(default_factory=list)


class ReasoningResult(BaseModel):
    """定义推理接口返回给应用层和前端的统一结果模型。

    该模型是 TKG 推理模块的标准输出，包含原始请求、参与推理的图
    快照、候选未来关系集合以及生成时间，用于前端可视化和实验评估。

    Attributes:
        request: 原始推理请求对象。
        snapshot: 本次推理所使用的图快照上下文。
        hypotheses: 推理得到的未来关系候选列表。
        generated_at: 当前结果生成的系统时间。
    """

    request: ReasoningRequest
    snapshot: Optional[TemporalGraphSnapshot] = None
    hypotheses: List[ReasoningHypothesis] = Field(default_factory=list)
    generated_at: datetime
