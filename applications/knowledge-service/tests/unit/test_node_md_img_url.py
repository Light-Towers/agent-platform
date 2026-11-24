# -*- coding: utf-8 -*-
"""图片 URL 拼接测试：bucket 与 object_name 之间必须有斜杠（2026-11-24 实踩）。"""

from knowledge_service.import_process.agent.nodes.node_md_img import build_image_url


def test_url_has_slash_between_bucket_and_object():
    url = build_image_url("minio:9000", "kb-import-bucket", "images/a.png", False)
    assert url == "http://minio:9000/kb-import-bucket/images/a.png"
    assert "kb-import-bucketimages" not in url


def test_url_https():
    url = build_image_url("minio:9000", "kb-import-bucket", "images/a.png", True)
    assert url == "https://minio:9000/kb-import-bucket/images/a.png"


def test_url_nested_object_path():
    # 历史 miss：object_name 是 images/知识图谱/xxx.jpg（多级目录）
    url = build_image_url("minio:9000", "kb-import-bucket", "images/知识图谱/xxx.jpg", False)
    assert url == "http://minio:9000/kb-import-bucket/images/知识图谱/xxx.jpg"
