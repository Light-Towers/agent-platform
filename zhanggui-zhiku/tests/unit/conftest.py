# -*- coding: utf-8 -*-
"""
conftest.py —— 本目录所有单元测试的共享配置。

【重要】本套测试刻意不依赖任何重型依赖（torch / langchain / magic-pdf /
pymilvus / transformers 等）。仅依赖 pytest + numpy + python-dotenv，
可在纯逻辑环境下独立运行。

此文件的作用：将「项目仓库根目录」加入 sys.path，使测试文件能直接
`import app.core.config` / `import app.utils.*` 等纯逻辑模块。
（pytest 默认的 prepend import 模式会把 tests/unit 而非仓库根加入
sys.path，因此需要这里手动补上仓库根。）
"""

import sys
from pathlib import Path

# tests/unit/conftest.py -> parent=tests/unit -> parent.parent=tests -> parent.parent.parent=repo_root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
