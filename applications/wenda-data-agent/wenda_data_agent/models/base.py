"""模型基类：CRUD 接口抽象。"""

from abc import ABC, abstractmethod
from typing import Any


class BaseModel(ABC):
    """模型基类：定义 CRUD 接口。"""

    def __init__(self, pool=None) -> None:
        self._pool = pool

    @abstractmethod
    async def create(self, data: dict[str, Any]) -> None: ...

    @abstractmethod
    async def read(self, key: Any) -> Any: ...

    @abstractmethod
    async def update(self, key: Any, data: dict[str, Any]) -> None: ...

    @abstractmethod
    async def delete(self, key: Any) -> None: ...
