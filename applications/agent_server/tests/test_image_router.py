# -*- coding: utf-8 -*-
"""图片代理端点测试：路径/桶/MIME 校验（plan-image-qa-fullstack §刀1）。只测纯判定，不发网络。"""

from agent_server.api.image_router import _safe_object_path


class TestSafeObjectPath:
    def test_normal_path_ok(self):
        assert _safe_object_path("images/20260101/task/a.png") == "images/20260101/task/a.png"

    def test_reject_absolute(self):
        assert _safe_object_path("/etc/passwd") is None

    def test_reject_dotdot(self):
        assert _safe_object_path("images/../../secret.png") is None

    def test_reject_backslash(self):
        assert _safe_object_path("images\\evil.png") is None

    def test_reject_empty_segment(self):
        assert _safe_object_path("images//a.png") is None

    def test_reject_dot_segment(self):
        assert _safe_object_path("images/./a.png") is None

    def test_reject_empty(self):
        assert _safe_object_path("") is None
