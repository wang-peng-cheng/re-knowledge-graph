# Backend Tests Guide

## 1. 测试总控台环境配置说明

### 1.1 推荐运行方式

- 统一推荐在项目根目录执行模块化命令：

```bash
python -m backend.tests.run_ablation_suite --mode v2_full
```

- 单文件直跑同样可用：

```bash
python backend/tests/run_ablation_suite.py --mode v2_full
```

### 1.2 Python 版本与核心依赖

- Python: `>=3.11`
- 关键依赖：
  - `httpx>=0.27.0`
  - `pydantic>=2.8.0`
  - `pydantic-settings>=2.4.0`
  - `python-dotenv>=1.0.1`
  - `PyYAML>=6.0.2`
  - `neo4j>=5.23.0`，仅在 `run_final_pipeline.py --write-neo4j` 时需要

### 1.3 硬件与运行资源要求

- CPU: 建议 `4` 核及以上
- 内存: 建议 `16GB` 及以上
- GPU: 若启用显存阈值校验且阈值 `< 1.0`，需要系统可执行 `nvidia-smi`
- 网络: 需要可访问 `QWEN_BASE_URL` 对应模型服务

### 1.4 环境变量要求

- `QWEN_BASE_URL`: Qwen/OpenAI 兼容服务地址
- `QWEN_API_KEY`: 模型访问密钥
- `QWEN_MODEL`: 模型名，当前默认推荐 `qwen3:8b`
- `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` / `NEO4J_DATABASE`: 仅在显式开启 Neo4j 写入时需要

### 1.5 配置文件参数说明

示例文件见 [ablation_suite.example.yaml](file:///d:/A_Work_Space/RE/re-knowledge-graph/backend/tests/ablation_suite.example.yaml)。

| 参数 | 说明 |
| --- | --- |
| `mode` | 消融实验模式，允许值：`baseline_v1`、`v2_no_filter`、`v2_no_reduce`、`v2_full` |
| `dataset` | 数据集路径，推荐使用根目录 `data/raw/*.json` |
| `relation_mapping_path` | 关系映射文件路径，默认 `data/raw/rel_info.json` |
| `docs` | 参与实验的文档数量 |
| `batch_size` | 每批调度的文档数 |
| `max_processes` | 文档级并发槽位上限 |
| `max_concurrency` | 单文档 chunk 并发上限 |
| `gpu_memory_threshold` | GPU 显存占用阈值，范围 `(0,1]`；取 `1.0` 时跳过 GPU 校验 |
| `document_timeout_seconds` | 单文档总超时 |
| `suite_timeout_seconds` | 整套实验总超时 |
| `request_timeout_seconds` | 单次 Qwen HTTP 请求超时 |
| `experiment_group_id` | 显式指定实验分组标识 |
| `qwen_base_url` / `qwen_api_key` / `qwen_model` | 用于覆盖环境变量的可选字段 |

## 2. CLI 命令示例

### 2.1 基线模型生抽模式

```bash
python -m backend.tests.run_ablation_suite ^
  --mode baseline_v1 ^
  --dataset data/raw/dev.json ^
  --docs 10 ^
  --batch-size 1 ^
  --max-processes 1
```

### 2.2 移除级联过滤的剥离模式

```bash
python -m backend.tests.run_ablation_suite ^
  --mode v2_no_filter ^
  --dataset data/raw/dev.json ^
  --docs 10 ^
  --batch-size 2 ^
  --max-processes 2 ^
  --max-concurrency 4
```

### 2.3 关闭 D-S 证据融合的降级模式

```bash
python -m backend.tests.run_ablation_suite ^
  --mode v2_no_reduce ^
  --dataset data/raw/dev.json ^
  --docs 10 ^
  --batch-size 2 ^
  --max-processes 2 ^
  --max-concurrency 4
```

### 2.4 神经符号完整版模式

```bash
python -m backend.tests.run_ablation_suite ^
  --mode v2_full ^
  --dataset data/raw/dev.json ^
  --docs 10 ^
  --batch-size 2 ^
  --max-processes 2 ^
  --max-concurrency 4 ^
  --gpu-memory-threshold 0.85
```

### 2.5 使用 YAML 配置一键启动

```bash
python -m backend.tests.run_ablation_suite --config backend/tests/ablation_suite.example.yaml
```

### 2.6 运行四模式冒烟矩阵

```bash
python -m backend.tests.run_ablation_smoke_batch ^
  --docs 2 ^
  --batch-size 1 ^
  --max-processes 1 ^
  --max-concurrency 2
```

### 2.7 自定义数据集路径、批次大小、并发数

```bash
python -m backend.tests.run_ablation_suite ^
  --mode v2_full ^
  --dataset data/raw/train_annotated.json ^
  --docs 20 ^
  --batch-size 4 ^
  --max-processes 2 ^
  --max-concurrency 6 ^
  --document-timeout-seconds 2400 ^
  --request-timeout-seconds 900
```

## 3. 实验结果归档目录结构说明

```text
re-knowledge-graph/
├─ data/
│  ├─ raw/
│  │  ├─ dev.json
│  │  ├─ rel_info.json
│  │  └─ train_annotated.json
│  └─ eval_results/
│     ├─ paper1-v2-full_20260606_120000/
│     │  ├─ experiment_config.yaml
│     │  ├─ metrics.json
│     │  └─ runtime.log
│     └─ smoke-v2_full_20260606_121500/
│        ├─ experiment_config.yaml
│        ├─ metrics.json
│        └─ runtime.log
└─ backend/
   └─ tests/
      ├─ run_ablation_suite.py
      ├─ run_ablation_smoke_batch.py
      ├─ run_ablation_experiments.py
      └─ TESTING_GUIDE.md
```

### 3.1 文件作用说明

- `data/raw/`: 原始数据资产目录；测试总控台会把输入数据镜像到这里并设置只读属性
- `data/eval_results/<group>_<timestamp>/experiment_config.yaml`: 本次实验的完整配置快照
- `data/eval_results/<group>_<timestamp>/metrics.json`: 总体指标、逐文档结果、失败统计
- `data/eval_results/<group>_<timestamp>/runtime.log`: 控制台同源日志，首行固定输出实验分组标识

### 3.2 调取方式

- 查看总体指标：打开 `metrics.json`
- 复现实验配置：打开 `experiment_config.yaml`
- 回溯执行过程与报错：打开 `runtime.log`

## 4. 常见问题排查

### 4.1 任务长时间无响应或疑似死锁

- 现有脚本已增加 `document_timeout_seconds` 与 `suite_timeout_seconds`
- 若仍频繁超时，优先降低：
  - `batch_size`
  - `max_processes`
  - `max_concurrency`
- 若单文档超长，优先提高 `document_timeout_seconds`，不要直接提高并发

### 4.2 路径错误或找不到数据集

- 优先确认数据文件位于 `data/raw/`
- 若传入相对路径，路径基准为项目根目录
- 如历史数据仍在 `backend/data/`，可先运行一次总控台，脚本会自动镜像到 `data/raw/`

### 4.3 权限不足或原始数据无法修改

- `data/raw/` 中文件被设置为只读是预期行为
- 如需替换原始数据，先移除只读属性，再覆盖文件
- Windows 可执行：

```powershell
attrib -R data\raw\dev.json
```

### 4.4 GPU 显存阈值校验失败

- 若设置了 `--gpu-memory-threshold 0.85` 一类严格阈值，系统必须能执行 `nvidia-smi`
- 若当前环境没有 GPU 监控能力，可先使用 `1.0` 跳过该检查

### 4.5 Qwen 连接失败或请求超时

- 先执行：

```bash
python -m backend.tests.test_qwen --request-timeout-seconds 120
```

- 若连通性测试失败，优先检查：
  - `QWEN_BASE_URL`
  - `QWEN_API_KEY`
  - `QWEN_MODEL`
  - 内网网络连通性

### 4.6 Neo4j 写入失败

- `run_final_pipeline.py` 默认不写 Neo4j
- 如需落库，显式传入 `--write-neo4j`
- 同时确认 `.env` 或环境变量中存在完整 Neo4j 凭据
