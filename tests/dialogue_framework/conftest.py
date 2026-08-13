"""dialogue_framework 专用 fixture。"""

import pytest


@pytest.fixture
def tmp_store_path(tmp_path):
    return tmp_path / "store.json"
