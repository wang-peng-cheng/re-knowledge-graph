from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


OUTPUT_PATH = Path(__file__).resolve().parent / "sample_docred.json"

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """配置脚本日志输出格式。"""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def retry(
    func: Callable[[], Any],
    *,
    attempts: int = 3,
    base_sleep_seconds: float = 1.0,
    max_sleep_seconds: float = 8.0,
    name: str = "operation",
) -> Any:
    """对可能不稳定的网络/IO 操作进行重试封装。"""

    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            sleep_s = min(max_sleep_seconds, base_sleep_seconds * (2 ** (i - 1)))
            logger.warning("%s 失败（第 %d/%d 次）：%s；%.1fs 后重试", name, i, attempts, exc, sleep_s)
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc


def normalize_docred_text(sents: Any) -> str:
    """将 DocRED 的 sents 字段拼接为完整文本。"""

    if not sents:
        return ""

    sentence_texts: list[str] = []
    for sent in sents:
        if isinstance(sent, str):
            sentence_texts.append(sent.strip())
        elif isinstance(sent, (list, tuple)):
            sentence_texts.append(" ".join([str(x) for x in sent]).strip())
        else:
            sentence_texts.append(str(sent).strip())
    return "\n".join([s for s in sentence_texts if s])


def build_preview_samples(items: Iterable[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """提取前若干条 DocRED 样本，并整理为便于预览的结构。"""

    samples: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if idx >= limit:
            break
        sents = item.get("sents") or item.get("sentences") or item.get("text") or []
        raw_text = normalize_docred_text(sents)
        doc_id = item.get("title") or item.get("doc_id") or item.get("id") or f"doc_{idx}"
        samples.append(
            {
                "document_id": str(doc_id),
                "raw_text": raw_text,
                "vertexSet": item.get("vertexSet", []),
                "labels": item.get("labels", []),
            }
        )
    return samples


def save_samples(samples: list[dict[str, Any]], output_path: Path) -> None:
    """将样本保存为 JSON 文件。"""

    payload = {
        "dataset": "DocRED",
        "split": "dev/validation",
        "sample_count": len(samples),
        "samples": samples,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def try_load_with_modelscope() -> Optional[list[dict[str, Any]]]:
    """优先使用 ModelScope 拉取 DocRED 数据集（更适合国内网络）。"""

    try:
        # 如果你没有安装 modelscope，请先执行：
        # pip install modelscope
        from modelscope.msdatasets import MsDataset  # type: ignore
    except Exception as exc:
        logger.info("ModelScope 不可用，将尝试备用下载方案。原因：%s", exc)
        return None

    candidate_dataset_names = [
        "docred",
        "DocRED",
        "thunlp/DocRED",
    ]
    candidate_splits = [
        "validation",
        "dev",
        "dev_rev",
    ]

    last_error: Exception | None = None
    for dataset_name in candidate_dataset_names:
        for split in candidate_splits:
            try:
                logger.info("尝试通过 ModelScope 加载数据集: name=%s split=%s", dataset_name, split)

                def _load():
                    return MsDataset.load(dataset_name, split=split)

                ds = retry(_load, attempts=3, name=f"ModelScope.load({dataset_name}:{split})")

                # MsDataset 返回对象通常可迭代/可索引，统一转为前 3 条 dict
                items: list[dict[str, Any]] = []
                for i in range(3):
                    item = ds[i]
                    if isinstance(item, dict):
                        items.append(item)
                    else:
                        items.append(dict(item))

                return build_preview_samples(items, limit=3)
            except Exception as exc:
                last_error = exc
                logger.warning("ModelScope 加载失败: name=%s split=%s | %s", dataset_name, split, exc)

    if last_error:
        logger.error("ModelScope 方案失败，最后一次错误：%s", last_error)
    return None


def try_load_with_requests() -> list[dict[str, Any]]:
    """使用 requests 从稳定镜像源下载 DocRED dev/validation JSON，并做重试。"""

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("未检测到 requests 库，请先执行: pip install requests") from exc

    session = requests.Session()
    session.headers.update({"User-Agent": "re-knowledge-graph/1.0"})

    candidate_urls = [
        # HuggingFace 镜像站（相对更适合国内网络）
        "https://hf-mirror.com/datasets/docred/resolve/main/dev.json",
        "https://hf-mirror.com/datasets/docred/resolve/main/dev_rev.json",
        "https://hf-mirror.com/datasets/docred/resolve/main/validation.json",
    ]

    def _download(url: str) -> list[dict[str, Any]]:
        logger.info("开始下载 DocRED 数据: %s", url)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"下载数据格式异常，期望 list，实际为 {type(data)}")
        return data

    last_error: Exception | None = None
    for url in candidate_urls:
        try:
            raw_docs = retry(lambda: _download(url), attempts=3, name=f"GET {url}")
            return build_preview_samples(raw_docs, limit=3)
        except Exception as exc:
            last_error = exc
            logger.warning("从该 URL 下载失败，将尝试下一个源：%s | %s", url, exc)

    assert last_error is not None
    raise RuntimeError(f"所有下载源均失败，最后错误：{last_error}") from last_error


def main() -> None:
    """下载 DocRED 数据集并生成 3 条样本预览文件。"""

    configure_logging()
    logger.info("开始下载并预览 DocRED 数据集（dev/validation）...")

    samples = try_load_with_modelscope()
    if samples is None:
        logger.info("切换到 requests 备用方案（镜像站下载）。")
        samples = try_load_with_requests()

    save_samples(samples, OUTPUT_PATH)
    print(f"✅ 已成功生成样本文件：{OUTPUT_PATH}")
    print("你可以打开 sample_docred.json 查看 DocRED 的 sents/vertexSet/labels 真实数据格式。")


if __name__ == "__main__":
    main()
