# -*- coding: utf-8 -*-
"""
test_config.py —— 验证 app/core/config.py 的配置单例与默认值。

【不依赖重型依赖，可在纯 pytest+numpy+python-dotenv 环境运行。】
本测试只 import app.core.config（仅依赖 os / dataclasses / pathlib / dotenv），
不会触发任何 torch / langchain / pymilvus 等重型导入。

重点验证：
1. settings 单例的默认值符合预期；
2. 刚修复过的 PROJECT_ROOT 确实是 pathlib.Path 实例，且指向仓库根；
3. 布尔/整型辅助解析（_as_bool / _as_int）行为正确。
"""

from pathlib import Path

from app.core.config import PROJECT_ROOT, Settings, _as_bool, _as_int, settings


def test_settings_default_milvus_url():
    # 掌柜智库默认 Milvus 地址
    assert settings.milvus_url == "http://localhost:19530"


def test_settings_default_app_port_is_int_8000():
    # 端口应为 int 类型，默认 8000
    assert isinstance(settings.app_port, int)
    assert settings.app_port == 8000


def test_settings_default_mongo_db_name():
    assert settings.mongo_db_name == "zhanggui-zhiku"


def test_settings_default_cors_origins():
    assert settings.cors_origins == "http://localhost:8000"


def test_settings_default_cors_allow_credentials_is_true_bool():
    # 应为真正的 bool True（之前曾因类型问题需重点验证）
    assert settings.cors_allow_credentials is True
    assert isinstance(settings.cors_allow_credentials, bool)


def test_settings_default_app_host():
    assert settings.app_host == "0.0.0.0"


def test_settings_default_collections():
    assert settings.chunks_collection == "kb_chunks"
    assert settings.entity_name_collection == "kb_entity_names"
    assert settings.item_name_collection == "kb_item_names"


def test_settings_default_neo4j_and_minio():
    assert settings.neo4j_uri == "bolt://localhost:7687"
    assert settings.minio_endpoint == "localhost:9000"


def test_project_root_is_path_instance():
    # 刚修复的点：PROJECT_ROOT 必须是 pathlib.Path，而非 str
    assert isinstance(PROJECT_ROOT, Path)


def test_project_root_points_to_repo_root():
    # PROJECT_ROOT 应解析为仓库根目录，且其中包含 app/ 包
    assert PROJECT_ROOT.is_dir()
    assert (PROJECT_ROOT / "app").is_dir()
    assert (PROJECT_ROOT / "app" / "core" / "config.py").is_file()


def test_settings_is_dataclass_singleton():
    # import 多次返回的 settings 应为同一对象（模块级单例）
    from app.core.config import settings as settings2

    assert settings is settings2
    assert isinstance(settings, Settings)


def test_as_bool_variants():
    # 真值识别
    assert _as_bool("True") is True
    assert _as_bool("true") is True
    assert _as_bool("1") is True
    # 非真值
    assert _as_bool("false") is False
    assert _as_bool("0") is False
    assert _as_bool("yes") is False
    # 空值回落默认
    assert _as_bool(None, True) is True
    assert _as_bool(None, False) is False


def test_as_int_variants():
    assert _as_int("8080", 8000) == 8080
    assert isinstance(_as_int("8080", 8000), int)
    # 空值回落默认
    assert _as_int(None, 8000) == 8000
    # 非法值回落默认
    assert _as_int("not-a-number", 8000) == 8000
    assert _as_int("", 8000) == 8000
