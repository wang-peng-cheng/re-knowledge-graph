from __future__ import annotations

"""这个函数是：
    提供实验运行器的共享工具函数。
"""

import asyncio
import importlib
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Iterable, Mapping, TypeVar
from uuid import uuid4

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
TESTS_DIR = BACKEND_DIR / "tests"
ROOT_DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = ROOT_DATA_DIR / "raw"
EVAL_RESULTS_DIR = ROOT_DATA_DIR / "eval_results"
LEGACY_DATA_DIR = BACKEND_DIR / "data"
AVAILABLE_LLM_PROVIDERS: tuple[str, ...] = ("qwen", "glm", "deepseek")

AVAILABLE_MODES: tuple[str, ...] = (
    "baseline_v1",
    "v2_no_filter",
    "v2_no_reduce",
    "v2_full",
)

MODE_LABELS: dict[str, str] = {
    "baseline_v1": "基线模型生抽模式",
    "v2_no_filter": "移除级联过滤的剥离模式",
    "v2_no_reduce": "关闭 D-S 证据融合的降级模式",
    "v2_full": "神经符号完整版模式",
}

DEFAULT_DATASET = "data/raw/dev.json"
DEFAULT_REL_INFO = "data/raw/rel_info.json"

T = TypeVar("T")


@dataclass(slots=True)
class SuiteConfig:
    """Normalized runtime configuration for experiment runners."""

    mode: str
    dataset: str = DEFAULT_DATASET
    relation_mapping_path: str = DEFAULT_REL_INFO
    docs: int = 10
    batch_size: int = 1
    max_processes: int = 1
    max_concurrency: int = 4
    gpu_memory_threshold: float = 1.0
    document_timeout_seconds: float = 1800.0
    suite_timeout_seconds: float = 21600.0
    request_timeout_seconds: float = 900.0
    experiment_group_id: str | None = None
    output_root: str = "data/eval_results"
    llm_provider: str = "qwen"
    qwen_base_url: str | None = None
    qwen_api_key: str | None = None
    qwen_model: str | None = None
    glm_base_url: str | None = None
    glm_api_key: str | None = None
    glm_model: str | None = None
    deepseek_base_url: str | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None

    def validate(self) -> None:
        """Validate runtime configuration before execution starts."""

        if self.mode not in AVAILABLE_MODES:
            raise ValueError(f"非法实验模式: {self.mode}，允许值为: {', '.join(AVAILABLE_MODES)}")
        normalized_provider = self.llm_provider.strip().lower()
        if normalized_provider not in AVAILABLE_LLM_PROVIDERS:
            raise ValueError(
                f"非法 llm_provider: {self.llm_provider}，允许值为: {', '.join(AVAILABLE_LLM_PROVIDERS)}"
            )
        self.llm_provider = normalized_provider
        if self.docs <= 0:
            raise ValueError("docs 必须为正整数。")
        if self.batch_size <= 0:
            raise ValueError("batch_size 必须为正整数。")
        if self.max_processes <= 0:
            raise ValueError("max_processes 必须为正整数。")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency 必须为正整数。")
        if not 0 < self.gpu_memory_threshold <= 1.0:
            raise ValueError("gpu_memory_threshold 必须位于 (0, 1] 区间。")
        if self.document_timeout_seconds <= 0:
            raise ValueError("document_timeout_seconds 必须大于 0。")
        if self.suite_timeout_seconds <= 0:
            raise ValueError("suite_timeout_seconds 必须大于 0。")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds 必须大于 0。")

    def to_log_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML safe config snapshot for logging and archiving."""

        payload = asdict(self)
        payload["mode_label"] = MODE_LABELS[self.mode]
        return payload

    def resolve_llm_overrides(self) -> dict[str, str | None]:
        """Return provider-specific runtime overrides for the current suite config."""

        provider_overrides = {
            "qwen": {
                "base_url": self.qwen_base_url,
                "api_key": self.qwen_api_key,
                "model": self.qwen_model,
            },
            "glm": {
                "base_url": self.glm_base_url,
                "api_key": self.glm_api_key,
                "model": self.glm_model,
            },
            "deepseek": {
                "base_url": self.deepseek_base_url,
                "api_key": self.deepseek_api_key,
                "model": self.deepseek_model,
            },
        }
        return dict(provider_overrides[self.llm_provider])


@dataclass(slots=True)
class ExperimentPaths:
    """Fixed archive paths for a single experiment run."""

    archive_dir: Path
    metrics_path: Path
    config_path: Path
    runtime_log_path: Path


def bootstrap_project_paths() -> None:
    """Ensure project and backend roots are importable for direct script runs."""

    for candidate in (PROJECT_ROOT, BACKEND_DIR):
        candidate_text = str(candidate)
        if candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)


def resolve_project_path(path_text: str) -> Path:
    """Resolve a path against the project root unless already absolute."""

    candidate = Path(path_text)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def sanitize_component(value: str) -> str:
    """Sanitize a value for safe file and directory naming."""

    allowed = [char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value.strip()]
    sanitized = "".join(allowed).strip("-._")
    return sanitized or "unknown"


def chunked(items: list[T], size: int) -> list[list[T]]:
    """Split a list into deterministic batches."""

    return [items[index:index + size] for index in range(0, len(items), size)]


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load a YAML config file as a dictionary."""

    if not config_path.exists():
        raise FileNotFoundError(f"未找到 YAML 配置文件: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("YAML 配置顶层必须为映射对象。")
    return dict(payload)


def write_yaml_file(path: Path, payload: Mapping[str, Any]) -> None:
    """Persist a YAML file using stable formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(dict(payload), handle, allow_unicode=False, sort_keys=False)


def write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    """Persist a JSON file with UTF-8 encoding and pretty formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def set_read_only(path: Path) -> None:
    """Apply a best-effort read-only bit to a file."""

    if not path.exists() or not path.is_file():
        return
    current_mode = path.stat().st_mode
    path.chmod(current_mode & ~stat.S_IWRITE)


def set_writable(path: Path) -> None:
    """Apply a best-effort writable bit to a file."""

    if not path.exists() or not path.is_file():
        return
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IWRITE)


def ensure_registered_raw_file(source_path: Path) -> Path:
    """Copy a dataset or metadata file into ``data/raw`` and mark it read-only."""

    if not source_path.exists():
        raise FileNotFoundError(f"未找到原始数据文件: {source_path}")

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    target_path = RAW_DATA_DIR / source_path.name
    if source_path.resolve() != target_path.resolve():
        if target_path.exists():
            set_writable(target_path)
        shutil.copy2(source_path, target_path)
    set_read_only(target_path)
    return target_path


def ensure_standard_data_tree() -> None:
    """Create the standardized root-level data directory tree."""

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_default_raw_assets() -> tuple[Path, Path]:
    """Register legacy backend data files into the new root ``data/raw`` tree."""

    dataset_path = ensure_registered_raw_file(LEGACY_DATA_DIR / "dev.json")
    relation_mapping_path = ensure_registered_raw_file(LEGACY_DATA_DIR / "rel_info.json")
    return dataset_path, relation_mapping_path


def build_suite_config(
    *,
    cli_values: Mapping[str, Any],
    yaml_values: Mapping[str, Any] | None = None,
) -> SuiteConfig:
    """Merge YAML values with CLI values, where CLI always wins."""

    merged: dict[str, Any] = {}
    if yaml_values:
        merged.update(yaml_values)

    for key, value in cli_values.items():
        if value is not None:
            merged[key] = value

    config = SuiteConfig(**merged)
    config.validate()
    return config


def create_experiment_paths(group_id: str) -> ExperimentPaths:
    """Create the fixed archive layout for a single experiment group."""

    ensure_standard_data_tree()
    timestamp_text = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = EVAL_RESULTS_DIR / f"{sanitize_component(group_id)}_{timestamp_text}"
    archive_dir.mkdir(parents=True, exist_ok=False)
    return ExperimentPaths(
        archive_dir=archive_dir,
        metrics_path=archive_dir / "metrics.json",
        config_path=archive_dir / "experiment_config.yaml",
        runtime_log_path=archive_dir / "runtime.log",
    )


def build_experiment_group_id(mode: str, explicit_group_id: str | None = None) -> str:
    """Build a unique experiment group identifier."""

    if explicit_group_id:
        return sanitize_component(explicit_group_id)
    return f"{sanitize_component(mode)}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"


def setup_run_logger(paths: ExperimentPaths, group_id: str, config: SuiteConfig) -> logging.Logger:
    """Configure one logger that writes to console and persistent runtime log."""

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    logger = logging.getLogger("backend.tests")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.FileHandler(paths.runtime_log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    logger.info("实验分组标识=%s", group_id)
    logger.info("实验归档目录=%s", paths.archive_dir)
    logger.info("实验核心配置=%s", json.dumps(config.to_log_dict(), ensure_ascii=False, sort_keys=True))
    return logger


def validate_python_dependencies() -> None:
    """Verify required third-party dependencies are importable."""

    required_modules = (
        ("yaml", "PyYAML"),
        ("dotenv", "python-dotenv"),
        ("httpx", "httpx"),
        ("pydantic", "pydantic"),
    )
    missing_packages: list[str] = []
    for module_name, package in required_modules:
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing_packages.append(package)
    if missing_packages:
        raise RuntimeError(f"缺少必要依赖: {', '.join(missing_packages)}")


def validate_gpu_memory_threshold(threshold: float) -> None:
    """Best-effort GPU memory guard using ``nvidia-smi`` when threshold is strict."""

    if threshold >= 1.0:
        return

    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "已配置 GPU 显存阈值，但当前环境无法执行 nvidia-smi，无法完成资源校验。"
        ) from exc

    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        total_memory = float(parts[0])
        used_memory = float(parts[1])
        if total_memory <= 0:
            continue
        usage_ratio = used_memory / total_memory
        if usage_ratio > threshold:
            raise RuntimeError(
                f"GPU 显存占用超阈值: 当前 {usage_ratio:.4f}，阈值 {threshold:.4f}。"
            )


def validate_runtime_inputs(config: SuiteConfig) -> tuple[Path, Path]:
    """Validate data paths and register them into the standardized raw tree."""

    dataset_source = resolve_project_path(config.dataset)
    relation_mapping_source = resolve_project_path(config.relation_mapping_path)

    dataset_path = ensure_registered_raw_file(dataset_source)
    relation_mapping_path = ensure_registered_raw_file(relation_mapping_source)
    return dataset_path, relation_mapping_path


def validate_suite_environment(config: SuiteConfig) -> tuple[Path, Path]:
    """Run all dependency and resource checks before execution starts."""

    validate_python_dependencies()
    ensure_standard_data_tree()
    validate_gpu_memory_threshold(config.gpu_memory_threshold)
    return validate_runtime_inputs(config)


async def run_with_timeout(label: str, awaitable: Awaitable[T], timeout_seconds: float) -> T:
    """Run an awaitable with timeout metadata in the raised exception."""

    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{label} 在 {timeout_seconds:.1f} 秒后超时。") from exc


def assert_metric_payload(metrics: Mapping[str, Any], *, label: str) -> None:
    """Validate metric payload ranges and count invariants."""

    required_keys = (
        "true_positive",
        "false_positive",
        "false_negative",
        "predicted_count",
        "gold_count",
        "precision",
        "recall",
        "f1",
    )
    missing = [key for key in required_keys if key not in metrics]
    if missing:
        raise AssertionError(f"{label} 缺失指标字段: {', '.join(missing)}")

    for key in ("true_positive", "false_positive", "false_negative", "predicted_count", "gold_count"):
        value = float(metrics[key])
        if value < 0:
            raise AssertionError(f"{label} 指标 {key} 不能为负数，实际为 {value}")

    for key in ("precision", "recall", "f1"):
        value = float(metrics[key])
        if value < 0.0 or value > 1.0:
            raise AssertionError(f"{label} 指标 {key} 必须位于 [0, 1]，实际为 {value}")

    predicted_count = float(metrics["predicted_count"])
    gold_count = float(metrics["gold_count"])
    true_positive = float(metrics["true_positive"])
    if true_positive > predicted_count:
        raise AssertionError(f"{label} true_positive 不能超过 predicted_count。")
    if true_positive > gold_count:
        raise AssertionError(f"{label} true_positive 不能超过 gold_count。")


def assert_non_empty_text(value: str, *, label: str, min_length: int = 1) -> None:
    """Assert that a text output is non-empty and reaches a minimum length."""

    stripped = value.strip()
    if len(stripped) < min_length:
        raise AssertionError(f"{label} 长度不足，至少需要 {min_length} 个字符，实际为 {len(stripped)}")


def summarize_failure_counts(results: Iterable[Mapping[str, Any]]) -> int:
    """Count how many per-document results contain a processing error marker."""

    return sum(1 for item in results if item.get("status") == "failed")


def build_manifest_payload(
    *,
    group_id: str,
    config: SuiteConfig,
    dataset_path: Path,
    relation_mapping_path: Path,
) -> dict[str, Any]:
    """Build a stable config payload for YAML archival."""

    payload = config.to_log_dict()
    payload["experiment_group_id"] = group_id
    payload["dataset"] = str(dataset_path)
    payload["relation_mapping_path"] = str(relation_mapping_path)
    payload["project_root"] = str(PROJECT_ROOT)
    return payload
