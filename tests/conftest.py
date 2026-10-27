"""pytest 全局配置。

两条原则:
  1. 单测不碰外部依赖: 不连 Milvus / Redis / Postgres / 任何 LLM Provider,
     全部用纯函数或假对象断言, 所以 CI 里 1 分钟内能跑完。
  2. 即使本机有 .env, 也要把 Provider Key 覆盖成占位符,
     避免哪条测试写错就真的发出付费请求。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 覆盖而不是 setdefault: 环境变量优先级高于 .env, 这样本地跑也不会打到真 Provider
os.environ["DASHSCOPE_API_KEY"] = "test-placeholder"
os.environ["DEEPSEEK_API_KEY"] = "test-placeholder"
os.environ["LOCAL_LLM_API_KEY"] = "test-placeholder"
os.environ["KB_ADMIN_TOKEN"] = "test-placeholder"
os.environ.setdefault("PERMISSION_MODE", "normal")
