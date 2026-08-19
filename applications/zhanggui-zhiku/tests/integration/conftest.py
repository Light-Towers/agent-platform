# -*- coding: utf-8 -*-
"""
conftest.py —— tests/integration 目录的共享配置。

【与 tests/unit 的区别】
- `tests/unit`：零外部依赖、零重型依赖，每次 PR 必跑。
- `tests/integration`：由仓库根 `test/01~05` 手测脚本归并而来，可能依赖
  重型依赖（torch / langchain / magic-pdf）、外部服务（Milvus / Neo4j /
  MongoDB / MinIO）或 GPU，仅在 Nightly / 手动触发时执行。

【本文件的作用】
将「项目仓库根目录」加入 sys.path，使测试文件能 `import app.*`。
（pytest 默认的 prepend import 模式只会把 tests/integration 加入 sys.path，
因此需要这里手动补上仓库根，与 tests/unit/conftest.py 保持同样做法。）

【跳过守卫约定】
各测试模块**各自**定义 `INTEGRATION_ENABLED` 常量（刻意不从 conftest 导入，
避免 tests/unit 与 tests/integration 两个同名 conftest 在 `pytest tests`
全量收集时产生模块名歧义）。需要外部服务或 GPU 的用例用
`@pytest.mark.skipif(not INTEGRATION_ENABLED, ...)` 守卫，
且重型 import 一律放进测试函数体内，确保：

    pytest tests/integration

在**任何环境**下都能完成收集且不报错——缺环境时跳过，而不是 ImportError。

要真正执行这些用例，设置环境变量后再运行：

    ZHIKU_INTEGRATION=1 pytest tests/integration -q
"""

import sys
from pathlib import Path

# tests/integration/conftest.py -> integration -> tests -> 仓库根
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
