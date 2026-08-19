"""自定义异常类。"""


class DialogueFrameworkError(Exception):
    """dialogue-framework 基础异常。"""


class StoreError(DialogueFrameworkError):
    """Store 存储异常。"""


class RetrievalError(DialogueFrameworkError):
    """检索异常。"""


class FlowError(DialogueFrameworkError):
    """Flow 执行异常。"""


class GuardError(DialogueFrameworkError):
    """守卫拒绝异常。"""


class CommandError(DialogueFrameworkError):
    """命令解析/执行异常。"""
