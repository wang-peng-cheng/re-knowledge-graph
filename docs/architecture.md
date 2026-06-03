# 基于大模型的网络舆情时序关系抽取与推演系统架构设计

## 1. 全栈技术选型

### 前端

- **核心框架**: Next.js 15 + React 19 + TypeScript
  - 理由: 兼顾 SSR/CSR、路由组织、类型安全与后续部署灵活性，适合构建“上传解析 + 图谱探索 + 推理交互”的统一前端入口。
- **状态与数据层**: TanStack Query + Zustand
  - 理由: Query 负责服务端状态缓存与轮询，Zustand 负责时间轴、筛选器、选中子图等前端局部状态，足够轻量。
- **图谱可视化**: AntV G6 / Graphin
  - 理由: 对知识图谱节点、边、分组、布局、事件绑定支持成熟，便于构建“按时间演化播放”的动态图谱视图。
- **时序交互组件**: Apache ECharts
  - 理由: 适合实现时间轴、事件热度、关系演化趋势等分析图表，与图谱面板形成联动。
- **UI 组件**: shadcn/ui + Tailwind CSS
  - 理由: 轻量、可定制、工程落地快，不抢占核心建模精力。

### 后端

- **API 框架**: FastAPI
  - 理由: 类型驱动、文档友好、异步支持好，适合承接文件上传、URL 接入、任务调度和推理 API。
  - FastAPI 天生支持异步（Async），效率最高，适合高并发场景。
- **配置管理**: python-dotenv + Pydantic Settings
  - 理由: 强制从 `.env` 加载敏感配置，满足“绝不硬编码密钥”的安全约束。
- **ORM 与 MySQL 访问**: SQLAlchemy 2.x + Alembic + MySQL 8
  - 理由: 用于接入层原始文本、清洗状态、抽取任务、审计日志的稳妥存储；迁移体系成熟。
- **LLM / Agent 编排**: LangGraph + 本地 Qwen OpenAI-Compatible API
  - 理由: 非常适合实现“规划 Agent / 抽取 Agent / 质检 Agent / 裁决 Agent”的**多智能体**图式流程，学术包装感强且可扩展。
- **HTTP 客户端**: `httpx`
  - 理由: 与 FastAPI 异步栈天然兼容，适配内网 Qwen API 调用。

### 图数据库

- **首选**: Neo4j 5 + APOC + Graph Data Science (GDS)
  - 理由: 对时序属性、路径查询、图算法和可视化生态最成熟，适合构建时态属性图（Temporal Property Graph）。
  - TKG 存储策略: 采用“事件边 + 时间区间属性 + 快照投影”混合建模。关系边保留 `valid_from`、`valid_to`、`observed_at`、`confidence`、`source_doc_id` 等字段。
  - TKG 推理优势: 便于将历史观测子图投影为时间窗口快照，再结合 LLM 生成候选关系、写回候选层或预测层。

### 为什么这套组合最适合本项目

- **对 RE 模块友好**: LangGraph 能自然表达 Multi-Agent 零样本抽取、自我反思、交叉投票与降噪闭环。
- **对 TKG 模块友好**: Neo4j 的属性图模型适合存储“同一关系在不同时间段的演化状态”，前端可直接按时间过滤重渲染。
- **对工程安全友好**: FastAPI + Pydantic Settings + `.env` 组合可以把安全约束前置到配置层。
- **对跨平台友好**: 本地 Windows 开发与 Linux 服务器部署都较平滑，避免使用对 Windows 支持差的重型方案。

## 2. 推荐目录结构

```text
re-knowledge-graph/
|-- docs/
|   `-- architecture.md（本文件）
|-- backend/
|   |-- .env.example
|   |-- pyproject.toml
|   `-- app/
|       |-- __init__.py
|       |-- main.py
|       |-- api/
|       |   |-- __init__.py
|       |   `-- v1/
|       |       |-- __init__.py
|       |       `-- routes/
|       |           |-- __init__.py
|       |           |-- system.py
|       |           `-- workflow.py
|       |-- core/
|       |   |-- __init__.py
|       |   `-- config.py
|       |-- domain（模型）/
|       |   |-- __init__.py
|       |   `-- models.py
|       |-- adapters（大模型适配）/
|       |   |-- __init__.py
|       |   `-- llm/
|       |       |-- __init__.py
|       |       `-- qwen_client.py
|       |-- repositories（数据库仓储）/
|       |   |-- __init__.py
|       |   |-- graph_repository.py
|       |   `-- mysql_repository.py
|       |-- services（核心业务逻辑）/
|       |   |-- __init__.py
|       |   |-- agentic_re_service.py
|       |   |-- cleaning_service.py
|       |   |-- graph_service.py
|       |   |-- ingestion_service.py
|       |   `-- reasoning_service.py
|       `-- pipeline/
|           |-- __init__.py
|           `-- e2e_pipeline.py
|-- frontend/
|   `-- (后续按 Next.js App Router 初始化)
`-- deploy/
    `-- (后续放置 docker-compose、nginx、systemd 等部署清单)
```

## 3. 核心目录说明

- `docs/architecture.md`
  - 架构总览、技术选型、目录设计说明，作为后续 Review 基线。
- `backend/.env.example`
  - 环境变量模板，统一声明 MySQL、Neo4j、Qwen API 等敏感配置项。
- `backend/pyproject.toml`
  - Python 项目依赖与工具配置入口。
- `backend/app/main.py`
  - 应用工厂与路由装配入口。
- `backend/app/core/config.py`
  - 从 `.env` 读取配置，集中管理跨环境参数。
- `backend/app/domain/models.py`
  - Pydantic 领域模型，定义文档、实体、关系、时序图谱、推理请求与结果等核心数据结构。
- `backend/app/adapters/llm/qwen_client.py`
  - 封装对本地 Qwen API 的调用接口，屏蔽底层协议差异。
- `backend/app/repositories/mysql_repository.py`
  - 管理 MySQL 中原始文档、脏数据、处理状态和任务信息。
- `backend/app/repositories/graph_repository.py`
  - 管理 Neo4j 中的实体、关系、时间属性和查询投影。
- `backend/app/services/ingestion_service.py`
  - 负责 URL / 文件接入、解析调度与原始记录入库。
- `backend/app/services/cleaning_service.py`
  - 负责脏数据清洗、切片、去噪与抽取前预处理。
- `backend/app/services/agentic_re_service.py`
  - 项目最核心模块之一，承载 Multi-Agent 零样本关系抽取与自校验流程。
- `backend/app/services/graph_service.py`
  - 负责将抽取结果转化为时态图写入请求，并支持时间窗口查询。
- `backend/app/services/reasoning_service.py`
  - 项目最核心模块之一，面向 TKG Extrapolation，负责候选未来关系推演接口。
- `backend/app/pipeline/e2e_pipeline.py`
  - 串起“接入 -> 清洗 -> 抽取 -> 入图 -> 推理”的端到端编排骨架。

## 4. 架构上的学术包装建议

- **RE 卖点命名**: `Multi-Agent Zero-Shot Temporal Relation Extraction with Self-Denoising`
- **TKG 卖点命名**: `LLM-Augmented Temporal Knowledge Graph Extrapolation for Public Opinion Evolution`
- **系统范式**: “以时态属性图为记忆底座，以多智能体大模型为抽取与推理引擎”
- **论文叙事建议**:
  - 先强调真实舆情数据噪声高、关系类型开放、时间表达模糊。
  - 再强调多智能体协作比单 Agent 更适合做开放关系抽取与自我纠错。
  - 最后强调图谱不是静态展示，而是面向演化分析与未来关系推演的时序认知底座。
