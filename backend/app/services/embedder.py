import logging
import os
from pathlib import Path
from typing import List

from app.core.config import settings

logger = logging.getLogger(__name__)

_model = None


def _ensure_model_local() -> str:
    """把模型文件拉到本地，优先用 ModelScope（国内），失败再回退 HuggingFace。

    同时跳过 safetensors 格式，避免重复下载体积巨大的 model.safetensors。
    如果本地缓存已经存在，直接复用，避免每次重启都走网络校验。
    """
    cache_root = Path.home() / ".cache" / "surgery-rag"
    ignore_patterns = [
        "*.safetensors",
        "*.safetensors.index.json",
        "*.bin.index.json",
        "*.msgpack",
    ]

    # ModelScope 缓存路径结构：cache_dir/models/{org}--{repo}/snapshots/{revision}
    ms_cache_dir = cache_root / "modelscope"
    ms_model_dir = (
        ms_cache_dir
        / "models"
        / settings.EMBEDDING_MODEL.replace("/", "--")
        / "snapshots"
        / "master"
    )
    if (ms_model_dir / "pytorch_model.bin").exists() or (ms_model_dir / "model.safetensors").exists():
        logger.info("Using cached embedding model at %s", ms_model_dir)
        return str(ms_model_dir)

    # 优先尝试 ModelScope 国内下载
    try:
        from modelscope.hub.snapshot_download import snapshot_download as ms_snapshot_download

        ms_cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading model %s from ModelScope...", settings.EMBEDDING_MODEL)
        local_path = ms_snapshot_download(
            settings.EMBEDDING_MODEL,
            cache_dir=str(ms_cache_dir),
            ignore_file_pattern=ignore_patterns,
        )
        logger.info("Model downloaded from ModelScope: %s", local_path)
        return local_path
    except Exception as e:
        logger.warning("ModelScope download failed: %s, fallback to HuggingFace", e)

    # 回退到 HuggingFace / HF_ENDPOINT
    from huggingface_hub import snapshot_download

    if settings.HF_ENDPOINT and not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = settings.HF_ENDPOINT

    logger.info("Downloading model %s from HuggingFace...", settings.EMBEDDING_MODEL)
    local_path = snapshot_download(
        repo_id=settings.EMBEDDING_MODEL,
        ignore_patterns=ignore_patterns,
    )
    logger.info("Model downloaded from HuggingFace: %s", local_path)
    return local_path


def _load_model():
    """懒加载 sentence-transformers 嵌入模型。"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        local_path = _ensure_model_local()
        logger.info("Loading embedding model from: %s", local_path)
        _model = SentenceTransformer(local_path)
        logger.info("Embedding model loaded")
    return _model


def warmup_embedder() -> None:
    """应用启动时预热 embedding 模型，避免第一个请求冷启动。"""
    _load_model()
    logger.info("Embedder warmup complete")


def embed_texts(texts: List[str]) -> List[List[float]]:
    """把文本列表编码成 1024 维归一化向量。

    Args:
        texts: 待编码文本列表。

    Returns:
        与输入等长的向量列表，每个向量是 float 列表。
    """
    if not texts:
        return []

    model = _load_model()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return embeddings.tolist()
