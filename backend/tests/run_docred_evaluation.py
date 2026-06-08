from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

for candidate in (PROJECT_ROOT, BACKEND_DIR):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from dotenv import load_dotenv

from app.adapters.llm.qwen_client import QwenClient
from app.core.config import get_settings
from app.domain.models import CleanedTextChunk, ExtractionResult, RawDocumentRecord, SourceType
from app.services.agentic_re_service import MultiAgentRelationExtractionService
from app.services.cleaning_service import TextCleaningService
from backend.tests.test_support import (
    DEFAULT_DATASET,
    DEFAULT_REL_INFO,
    SuiteConfig,
    assert_metric_payload,
    build_experiment_group_id,
    build_manifest_payload,
    create_experiment_paths,
    ensure_default_raw_assets,
    run_with_timeout,
    setup_run_logger,
    validate_suite_environment,
    write_json_file,
    write_yaml_file,
)

logger = logging.getLogger("backend.tests.docred_evaluation")

DEV_PATH = PROJECT_ROOT / DEFAULT_DATASET
REL_INFO_PATH = PROJECT_ROOT / DEFAULT_REL_INFO


@dataclass
class GoldEntity:
    """表示 DocRED 黄金实体的规范化信息。"""

    index: int
    primary_name: str
    aliases: set[str]
    entity_type: str


@dataclass
class GoldRelation:
    """表示用于评测的黄金关系三元组。"""

    relation_type: str
    head_primary_name: str
    tail_primary_name: str
    head_aliases: set[str]
    tail_aliases: set[str]


@dataclass
class PredRelation:
    """表示系统预测出的关系三元组。"""

    relation_type: str
    head_name: str
    tail_name: str


def configure_logging() -> None:
    """Compatibility no-op kept for callers importing this helper module."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )


def normalize_name(value: Any) -> str:
    """对实体名或关系名进行归一化，便于评测比对。"""

    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip("`'\"[](){}")
    return text


def load_json_file(path: Path) -> Any:
    """读取本地 JSON 文件并返回解析结果。"""

    if not path.exists():
        raise FileNotFoundError(f"未找到文件：{path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_raw_text_from_sents(sents: Sequence[Any]) -> str:
    """将 DocRED 的分句 token 序列拼接为适合抽取的原始文本。"""

    sentence_texts: List[str] = []
    for sent in sents:
        if isinstance(sent, str):
            sentence_texts.append(sent.strip())
        elif isinstance(sent, (list, tuple)):
            sentence_texts.append(" ".join(str(token) for token in sent).strip())
        else:
            sentence_texts.append(str(sent).strip())
    return "\n".join(item for item in sentence_texts if item)


def build_gold_entities(vertex_set: Sequence[Any]) -> Dict[int, GoldEntity]:
    """将 DocRED 的 vertexSet 转换为便于评测使用的黄金实体映射。"""

    gold_entities: Dict[int, GoldEntity] = {}
    for index, mentions in enumerate(vertex_set):
        aliases: set[str] = set()
        primary_name = ""
        entity_type = "UNKNOWN"

        if isinstance(mentions, list):
            for mention in mentions:
                if not isinstance(mention, dict):
                    continue
                mention_name = normalize_name(mention.get("name", ""))
                if mention_name:
                    aliases.add(mention_name)
                    if not primary_name:
                        primary_name = mention_name
                entity_type = str(mention.get("type", entity_type))

        if not primary_name:
            primary_name = f"entity_{index}"
            aliases.add(primary_name)

        gold_entities[index] = GoldEntity(
            index=index,
            primary_name=primary_name,
            aliases=aliases,
            entity_type=entity_type,
        )

    return gold_entities


def build_gold_relations(
    labels: Sequence[Any],
    gold_entities: Dict[int, GoldEntity],
    relation_mapping: Dict[str, str],
) -> List[GoldRelation]:
    """将 DocRED 标签转换为带文字关系名的黄金关系列表。"""

    gold_relations: List[GoldRelation] = []
    for label in labels:
        if not isinstance(label, dict):
            continue

        head_index = label.get("h")
        tail_index = label.get("t")
        relation_code = str(label.get("r", "")).strip()

        if not isinstance(head_index, int) or not isinstance(tail_index, int):
            continue
        if head_index not in gold_entities or tail_index not in gold_entities:
            continue

        head_entity = gold_entities[head_index]
        tail_entity = gold_entities[tail_index]
        relation_name = relation_mapping.get(relation_code, relation_code)

        gold_relations.append(
            GoldRelation(
                relation_type=normalize_name(relation_name),
                head_primary_name=head_entity.primary_name,
                tail_primary_name=tail_entity.primary_name,
                head_aliases=head_entity.aliases,
                tail_aliases=tail_entity.aliases,
            )
        )

    return gold_relations


def build_pred_relations(result: ExtractionResult) -> List[PredRelation]:
    """将系统抽取结果转换为可评测的关系三元组。"""

    entity_lookup: Dict[str, str] = {}
    for entity in result.entities:
        preferred_name = entity.canonical_name or entity.surface_form or entity.entity_id
        entity_lookup[entity.entity_id] = normalize_name(preferred_name)

    pred_relations: List[PredRelation] = []
    for relation in result.relations:
        head_name = entity_lookup.get(relation.head_entity_id, normalize_name(relation.head_entity_id))
        tail_name = entity_lookup.get(relation.tail_entity_id, normalize_name(relation.tail_entity_id))
        relation_type = normalize_name(relation.relation_type)

        if not head_name or not tail_name or not relation_type:
            continue

        pred_relations.append(
            PredRelation(
                relation_type=relation_type,
                head_name=head_name,
                tail_name=tail_name,
            )
        )

    return pred_relations


def entity_matches_aliases(predicted_name: str, gold_aliases: Iterable[str]) -> bool:
    """使用柔性子串包含规则判断预测实体是否命中黄金别名集合。

    命中条件：
    1. 预测实体与黄金 alias 完全一致。
    2. 预测实体包含在某个黄金 alias 中。
    3. 某个黄金 alias 包含在预测实体中。

    所有比较都通过 `normalize_name()` 统一执行，自动忽略大小写、连续空
    白和首尾包裹符号差异。
    """

    normalized_predicted = normalize_name(predicted_name)
    if not normalized_predicted:
        return False

    for alias in gold_aliases:
        normalized_alias = normalize_name(alias)
        if not normalized_alias:
            continue
        if normalized_predicted == normalized_alias:
            return True
        if normalized_predicted in normalized_alias:
            return True
        if normalized_alias in normalized_predicted:
            return True

    return False


def relation_matches(pred: PredRelation, gold: GoldRelation) -> bool:
    """判断一条预测关系是否与某条黄金关系匹配。"""

    if pred.relation_type != gold.relation_type:
        return False
    if not entity_matches_aliases(pred.head_name, gold.head_aliases):
        return False
    if not entity_matches_aliases(pred.tail_name, gold.tail_aliases):
        return False
    return True


def compute_relation_metrics(
    predicted_relations: Sequence[PredRelation],
    gold_relations: Sequence[GoldRelation],
) -> Dict[str, float]:
    """基于贪心一对一匹配计算 Precision、Recall 与 F1。"""

    matched_gold_indices: set[int] = set()
    true_positive = 0

    for pred in predicted_relations:
        matched_index = None
        for index, gold in enumerate(gold_relations):
            if index in matched_gold_indices:
                continue
            if relation_matches(pred, gold):
                matched_index = index
                break
        if matched_index is not None:
            matched_gold_indices.add(matched_index)
            true_positive += 1

    predicted_count = len(predicted_relations)
    gold_count = len(gold_relations)
    false_positive = predicted_count - true_positive
    false_negative = gold_count - true_positive

    precision = true_positive / predicted_count if predicted_count else 0.0
    recall = true_positive / gold_count if gold_count else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "true_positive": float(true_positive),
        "false_positive": float(false_positive),
        "false_negative": float(false_negative),
        "predicted_count": float(predicted_count),
        "gold_count": float(gold_count),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def build_document_record(doc: Dict[str, Any], index: int) -> RawDocumentRecord:
    """将 DocRED 文档包装为当前项目的原始文档模型。"""

    title = str(doc.get("title", f"docred_doc_{index}"))
    raw_text = build_raw_text_from_sents(doc.get("sents", []))

    return RawDocumentRecord(
        document_id=f"docred_eval_{index:03d}",
        source_type=SourceType.TXT,
        source_uri=f"docred://dev/{title}",
        raw_text=raw_text,
        created_at=datetime.now(),
        metadata={
            "dataset": "DocRED",
            "split": "dev",
            "title": title,
            "index": index,
            "source": "DocRED",
            "emotion": "",
            "city": "",
            "publish_time": "",
        },
    )


async def extract_single_document(
    index: int,
    doc: Dict[str, Any],
    relation_mapping: Dict[str, str],
    cleaning_service: TextCleaningService,
    extraction_service: MultiAgentRelationExtractionService,
    *,
    document_timeout_seconds: float = 1800.0,
) -> Dict[str, Any]:
    """对单篇 DocRED 文档执行清洗、抽取与评测准备。"""

    record = build_document_record(doc, index)
    chunks: List[CleanedTextChunk] = await run_with_timeout(
        f"DocRED 文档清洗[{record.document_id}]",
        cleaning_service.clean_document(record),
        document_timeout_seconds,
    )
    if len(chunks) <= 0:
        raise AssertionError(f"文档 {record.document_id} 清洗后 chunk 数必须大于 0。")
    target_schemas = sorted({str(name).strip() for name in relation_mapping.values() if str(name).strip()})
    result = await run_with_timeout(
        f"DocRED 文档抽取[{record.document_id}]",
        extraction_service.extract(record.document_id, chunks, target_schemas=target_schemas),
        document_timeout_seconds,
    )

    gold_entities = build_gold_entities(doc.get("vertexSet", []))
    gold_relations = build_gold_relations(doc.get("labels", []), gold_entities, relation_mapping)
    pred_relations = build_pred_relations(result)

    # 打印前3条黄金关系与预测关系，用于调试
    print(f"\n--- 调试文档: {doc.get('title')} ---")
    print("【前3条 黄金关系 (Gold)】:")
    for g in gold_relations[:3]:
        print(f"  ({g.head_primary_name}) -[{g.relation_type}]-> ({g.tail_primary_name})")
        
    print("\n【前3条 预测关系 (Pred)】:")
    for p in pred_relations[:3]:
        print(f"  ({p.head_name}) -[{p.relation_type}]-> ({p.tail_name})")
    print("----------------------------------\n")
    metrics = compute_relation_metrics(pred_relations, gold_relations)
    assert_metric_payload(metrics, label=f"DocRED 文档指标[{record.document_id}]")
    return {
        "status": "success",
        "document_id": record.document_id,
        "title": doc.get("title", f"docred_doc_{index}"),
        "chunk_count": len(chunks),
        "gold_relation_count": len(gold_relations),
        "pred_relation_count": len(pred_relations),
        "metrics": metrics,
    }


def build_qwen_client(*, request_timeout_seconds: float = 900.0) -> QwenClient:
    """构建评测脚本使用的大模型客户端。"""

    load_dotenv(BACKEND_DIR / ".env")

    try:
        settings = get_settings()
        logger.info("已从配置中心加载 Qwen 参数：base_url=%s, model=%s", settings.qwen_base_url, settings.qwen_model)
        return QwenClient(
            base_url=settings.qwen_base_url,
            api_key=settings.qwen_api_key,
            model=settings.qwen_model,
            timeout_seconds=request_timeout_seconds,
        )
    except Exception as exc:
        logger.warning("通过配置中心加载失败，将回退到环境变量直读模式：%s", exc)
        base_url = os.getenv("QWEN_BASE_URL", "http://10.109.118.166:11434/v1")
        api_key = os.getenv("QWEN_API_KEY", "EMPTY")
        model = os.getenv("QWEN_MODEL", "qwen3:8b")
        return QwenClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=request_timeout_seconds,
        )


def summarize_overall_metrics(per_doc_results: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    """汇总多篇文档的关系抽取评测指标。"""

    total_tp = 0.0
    total_fp = 0.0
    total_fn = 0.0
    total_pred = 0.0
    total_gold = 0.0

    for item in per_doc_results:
        metrics = item["metrics"]
        total_tp += metrics["true_positive"]
        total_fp += metrics["false_positive"]
        total_fn += metrics["false_negative"]
        total_pred += metrics["predicted_count"]
        total_gold += metrics["gold_count"]

    precision = total_tp / total_pred if total_pred else 0.0
    recall = total_tp / total_gold if total_gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "document_count": float(len(list(per_doc_results))) if not isinstance(per_doc_results, list) else float(len(per_doc_results)),
        "true_positive": total_tp,
        "false_positive": total_fp,
        "false_negative": total_fn,
        "predicted_count": total_pred,
        "gold_count": total_gold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def build_eval_report_filename(model_name: str, timestamp: datetime) -> str:
    """构建评测结果文件名，并清理不适合文件系统的模型名字符。"""

    safe_model_name = re.sub(r"[^A-Za-z0-9._-]+", "-", model_name.strip()) or "unknown-model"
    timestamp_text = timestamp.strftime("%Y%m%d_%H%M%S")
    return f"eval_{safe_model_name}_{timestamp_text}.json"


def parse_args() -> argparse.Namespace:
    """解析 DocRED 自动化评测参数。"""

    parser = argparse.ArgumentParser(description="DocRED 自动化评测脚本")
    parser.add_argument("--dataset", type=str, default=str(DEV_PATH), help="数据集路径")
    parser.add_argument("--relation-mapping-path", type=str, default=str(REL_INFO_PATH), help="关系映射路径")
    parser.add_argument("--docs", type=int, default=10, help="参与评测的文档数量")
    parser.add_argument("--document-timeout-seconds", type=float, default=1800.0, help="单文档超时秒数")
    parser.add_argument("--request-timeout-seconds", type=float, default=900.0, help="Qwen 请求超时秒数")
    parser.add_argument("--suite-timeout-seconds", type=float, default=21600.0, help="整套评测超时秒数")
    parser.add_argument("--experiment-group-id", type=str, default=None, help="显式指定实验分组标识")
    return parser.parse_args()


async def main() -> None:
    """运行 DocRED 自动化评测流程。"""

    args = parse_args()
    ensure_default_raw_assets()
    config = SuiteConfig(
        mode="baseline_v1",
        dataset=args.dataset,
        relation_mapping_path=args.relation_mapping_path,
        docs=args.docs,
        batch_size=1,
        max_processes=1,
        max_concurrency=1,
        document_timeout_seconds=args.document_timeout_seconds,
        suite_timeout_seconds=args.suite_timeout_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        experiment_group_id=args.experiment_group_id or "docred-eval",
    )
    config.validate()
    dataset_path, relation_mapping_path = validate_suite_environment(config)
    group_id = build_experiment_group_id("docred-eval", config.experiment_group_id)
    paths = create_experiment_paths(group_id)
    run_logger = setup_run_logger(paths, group_id, config)
    write_yaml_file(
        paths.config_path,
        build_manifest_payload(
            group_id=group_id,
            config=config,
            dataset_path=dataset_path,
            relation_mapping_path=relation_mapping_path,
        ),
    )

    relation_mapping = load_json_file(relation_mapping_path)
    dev_docs = load_json_file(dataset_path)
    if not isinstance(relation_mapping, dict):
        raise ValueError("rel_info.json 格式异常，顶层必须为字典。")
    if not isinstance(dev_docs, list):
        raise ValueError("dev.json 格式异常，顶层必须为列表。")

    target_docs = dev_docs[:config.docs]
    if len(target_docs) <= 0:
        raise AssertionError("DocRED 评测集为空，至少需要 1 篇文档。")

    run_logger.info("已加载 DocRED 文档 %d 篇，准备进行关系抽取评测。", len(target_docs))

    cleaning_service = TextCleaningService()
    qwen_client = build_qwen_client(request_timeout_seconds=config.request_timeout_seconds)
    extraction_service = MultiAgentRelationExtractionService(qwen_client=qwen_client)
    per_doc_results: List[Dict[str, Any]] = []

    try:
        for index, doc in enumerate(target_docs):
            title = doc.get("title", f"docred_doc_{index}")
            run_logger.info("开始处理第 %d/%d 篇文档：%s", index + 1, len(target_docs), title)
            try:
                doc_result = await extract_single_document(
                    index=index,
                    doc=doc,
                    relation_mapping=relation_mapping,
                    cleaning_service=cleaning_service,
                    extraction_service=extraction_service,
                    document_timeout_seconds=config.document_timeout_seconds,
                )
                per_doc_results.append(doc_result)
                run_logger.info(
                    "文档评测完成：title=%s | gold=%d | pred=%d | P=%.4f | R=%.4f | F1=%.4f",
                    doc_result["title"],
                    doc_result["gold_relation_count"],
                    doc_result["pred_relation_count"],
                    doc_result["metrics"]["precision"],
                    doc_result["metrics"]["recall"],
                    doc_result["metrics"]["f1"],
                )
            except Exception as exc:
                run_logger.exception("文档处理失败，已跳过：title=%s | 错误=%s", title, exc)
                per_doc_results.append(
                    {
                        "status": "failed",
                        "document_id": f"docred_eval_{index:03d}",
                        "title": title,
                        "chunk_count": 0,
                        "gold_relation_count": 0,
                        "pred_relation_count": 0,
                        "metrics": {
                            "true_positive": 0.0,
                            "false_positive": 0.0,
                            "false_negative": 0.0,
                            "predicted_count": 0.0,
                            "gold_count": 0.0,
                            "precision": 0.0,
                            "recall": 0.0,
                            "f1": 0.0,
                        },
                        "error": str(exc),
                    }
                )
    finally:
        await qwen_client.close()

    success_results = [item for item in per_doc_results if item.get("status") == "success"]
    if not success_results:
        raise RuntimeError("没有任何文档成功完成评测，无法计算最终指标。")

    overall = summarize_overall_metrics(success_results)
    assert_metric_payload(overall, label="DocRED 总体指标")

    metrics_payload = {
        "mode": "docred_evaluation",
        "document_count": len(target_docs),
        "success_count": len(success_results),
        "failure_count": len(per_doc_results) - len(success_results),
        "dataset": str(dataset_path),
        "relation_mapping_path": str(relation_mapping_path),
        "model_config": qwen_client.model,
        "overall_metrics": overall,
        "per_doc_details": per_doc_results,
    }
    write_json_file(paths.metrics_path, metrics_payload)
    run_logger.info("DocRED 评测归档已保存：%s", paths.archive_dir)


if __name__ == "__main__":
    asyncio.run(main())
