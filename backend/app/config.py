"""统一配置：从项目根 .env 读取。"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DASHSCOPE_API_KEY = os.environ["DASHSCOPE_API_KEY"]
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

LLM_MODEL = os.environ.get("LLM_MODEL", "qwen-plus")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentic_rag:agentic_rag@127.0.0.1:5432/agentic_rag",
)
# asyncpg 用标准 postgresql:// DSN（不带 +psycopg）
if DATABASE_URL.startswith("postgresql+"):
    DATABASE_URL = DATABASE_URL.split("+", 1)[0] + "://" + DATABASE_URL.split("://", 1)[1]

# 容器内运行但环境变量被 MCP 客户端清洗掉的兜底：默认走 compose 服务名
if "DATABASE_URL" not in os.environ and Path("/.dockerenv").exists():
    DATABASE_URL = "postgresql://agentic_rag:agentic_rag@postgres:5432/agentic_rag"

# 摄取范围（检索语料）：reference 不入库
INGEST_DIRS = ["docs/blog", "docs/basics"]

AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "6"))
TOP_K = int(os.environ.get("TOP_K", "5"))
