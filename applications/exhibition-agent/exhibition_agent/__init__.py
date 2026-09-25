"""exhibition-agent：会展行业 AI Agent 平台侧骨架。

按《跨项目接口契约 v1.1》接入 mingyang-warehouse，本包只做编排与契约消费，
不直连数据库（INV-6）、不引入 LangChain 全家桶、不实现写操作。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
