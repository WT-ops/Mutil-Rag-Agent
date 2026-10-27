
import json
import urllib.request
import urllib.error
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
cfg = dotenv_values(ROOT / ".env")

api_key = cfg.get("DASHSCOPE_API_KEY")
base_url = (cfg.get("DASHSCOPE_BASE_URL") or "").rstrip("/")

if not api_key or not base_url:
    raise SystemExit("配置错误：DASHSCOPE_API_KEY 或 BASE_URL 为空")

if not base_url.startswith("https://"):
    raise SystemExit("安全检查失败：BASE_URL 必须使用 HTTPS")

def call_api(path, payload):
    request = urllib.request.Request(
        base_url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)

    except urllib.error.HTTPError as exc:
        # 避免输出可能包含敏感信息的响应内容
        print(f"API 返回 HTTP {exc.code}")
        return None

    except Exception as exc:
        print("连接失败，错误类型：", type(exc).__name__)
        return None


print("========== Chat Model ==========")

chat = call_api(
    "/chat/completions",
    {
        "model": cfg.get("DASHSCOPE_CHAT_MODEL", "qwen-plus"),
        "messages": [
            {"role": "user", "content": "只回复 OK"}
        ],
        "max_tokens": 20,
    },
)

if chat and chat.get("choices"):
    print("Chat Model：测试成功")
else:
    print("Chat Model：测试失败")


print("========== Embedding ==========")

embedding = call_api(
    "/embeddings",
    {
        "model": cfg.get(
            "DASHSCOPE_EMBEDDING_MODEL",
            "text-embedding-v4",
        ),
        "input": ["Redis 连接异常诊断"],
        "dimensions": int(
            cfg.get("DASHSCOPE_EMBEDDING_DIM", "1024")
        ),
    },
)

if embedding and embedding.get("data"):
    dimension = len(embedding["data"][0]["embedding"])
    print("Embedding：测试成功")
    print("实际向量维度：", dimension)
else:
    print("Embedding：测试失败")