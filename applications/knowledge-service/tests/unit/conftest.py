# -*- coding: utf-8 -*-
"""
conftest.py —— 本目录所有单元测试的共享配置。

【重要】本套测试刻意不依赖任何重型依赖（torch / langchain / magic-pdf /
pymilvus / transformers 等）。仅依赖 pytest + numpy + python-dotenv，
可在纯逻辑环境下独立运行。

此文件的作用：将「项目仓库根目录」加入 sys.path，使测试文件能直接
`import knowledge_service.core.config` / `import knowledge_service.utils.*` 等纯逻辑模块。
（pytest 默认的 prepend import 模式会把 tests/unit 而非仓库根加入
sys.path，因此需要这里手动补上仓库根。）

另外把顶层 `eval` 重绑到本服务 eval/：agent_federation 以 editable 安装后其源码根
进入 sys.path，使 `applications/agent_federation/eval/` 成为可全局 import 的顶层 `eval`
包（workspace 同名冲突，见根 Makefile `eval` 目标注释）；若 pytest 启动阶段已把
`sys.modules['eval']` 绑到 federation 版，本目录 `from eval.metrics import ...` 会报
ModuleNotFoundError。重绑仅影响本 session，不改任何断言。
"""

import importlib
import importlib.util
import sys
from pathlib import Path

# tests/unit/conftest.py -> parent=tests/unit -> parent.parent=tests -> parent.parent.parent=repo_root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 丢弃可能已被 agent_federation 污染的顶层 `eval` 缓存，重新按 sys.path[0]=REPO_ROOT 解析。
for _name in [m for m in list(sys.modules) if m == "eval" or m.startswith("eval.")]:
    del sys.modules[_name]
importlib.invalidate_caches()

# 按文件路径强制将顶层 `eval` 绑定到本服务 eval/（不依赖 sys.path 排序，避免
# 可编辑安装注入的 federation 路径抢先）；submodule_search_locations 保证子模块可解。
_eval_dir = REPO_ROOT / "eval"
_spec = importlib.util.spec_from_file_location(
    "eval", _eval_dir / "__init__.py", submodule_search_locations=[str(_eval_dir)]
)
_eval_mod = importlib.util.module_from_spec(_spec)
sys.modules["eval"] = _eval_mod
_spec.loader.exec_module(_eval_mod)
