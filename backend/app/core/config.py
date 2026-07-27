from pydantic_settings import BaseSettings
import os


_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROJECT_ROOT = os.path.dirname(_BASE_DIR)


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/surgery_rag"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_REQUEST_TIMEOUT: int = 60

    # 文件上传配置（默认放到项目根目录的 uploads/，与代码分离）
    UPLOAD_DIR: str = os.path.join(_PROJECT_ROOT, "uploads")
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png"}

    # 分块配置
    CHUNK_SIZE: int = 400
    CHUNK_OVERLAP: int = 50
    # 病历级分块上限：一例完整病历尽量作为单个 chunk
    CASE_CHUNK_MAX_SIZE: int = 1500
    PDF_OCR_MIN_TEXT_LENGTH: int = 50
    PDF_OCR_DPI: int = 150

    # Embedding 配置（Milestone 2B 使用）
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIMENSION: int = 1024
    EMBEDDING_BATCH_SIZE: int = 32
    # Hugging Face 镜像，例如 https://hf-mirror.com；留空则走官方
    HF_ENDPOINT: str = ""

    # 检索配置（Milestone 3 使用）
    RETRIEVER_TOP_K_VECTOR: int = 10
    RETRIEVER_TOP_K_FULLTEXT: int = 10
    RETRIEVER_FUSION_K: int = 30          # RRF 常数（降低以增强向量检索的高排名权重）
    RETRIEVER_FINAL_TOP_K: int = 7        # 最终送入 LLM 的片段数（配合 k=30，7 段多兜底全文匹配）
    RETRIEVER_SIMILARITY_THRESHOLD: float = 0.62  # 由 evaluation/rag_baseline_10.json 初步校准
    RETRIEVER_DUAL_MATCH_MARGIN: float = 0.08
    RETRIEVER_FULLTEXT_THRESHOLD: float = 0.12
    CHAT_MEMORY_ROUNDS: int = 6           # 最近 N 轮对话

    # 内容安全配置（M5）
    INPUT_MAX_LENGTH: int = 2000              # 单条用户消息最大字符数
    ENABLE_CONTENT_FILTER: bool = True         # 是否启用输入越狱/诱导检测
    ENABLE_DANGER_SYMPTOM_CHECK: bool = True   # 是否启用危险症状关键词检测
    ENABLE_OUTPUT_FILTER: bool = True          # 是否启用输出内容安全检测

    # 查询改写配置
    ENABLE_LLM_QUERY_REWRITE: bool = True
    REWRITE_MAX_HISTORY: int = 6
    REWRITE_MODEL: str = "deepseek-chat"  # 可改为更轻量模型以降低成本

    # PGVector 配置
    VECTOR_COLLECTION_NAME: str = "surgery_docs"
    VECTOR_STORE_CONNECTION_STRING: str = ""  # 为空时复用 DATABASE_URL

    # LangSmith 配置（默认关闭）
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "surgery-rag"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"

    # Agent 模式预留
    ENABLE_AGENT_MODE: bool = False
    AGENT_MAX_ITERATIONS: int = 5

    # OCR 配置
    PADDLEOCR_LANG: str = "ch"
    PADDLEOCR_USE_GPU: bool = False

    class Config:
        env_file = os.path.join(_BASE_DIR, ".env")
        env_file_encoding = "utf-8"


settings = Settings()
