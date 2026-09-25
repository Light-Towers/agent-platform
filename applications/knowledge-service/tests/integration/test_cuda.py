# -*- coding: utf-8 -*-
"""
PyTorch 安装与 CUDA 可用性探测。

归并自：`test/03-cuda测试.py`（原为 try/except + print 的手测脚本）。

原脚本依次打印：PyTorch 版本、`torch.cuda.is_available()`、
`torch.cuda.device_count()`、`torch.cuda.get_device_name(0)`，
并注明「CPU 版显示 False 正常」。

改造要点：
- torch 是重型依赖（约 GB 级），用 `pytest.importorskip` 守卫，未安装时跳过而非报错；
- 原脚本第 4 条 `get_device_name(0)` 在无 GPU 机器上必然抛异常（原脚本靠 try/except
  兜住并打印失败），这里拆成独立用例并用 `torch.cuda.is_available()` 守卫，
  语义更准确：**无 GPU 是跳过，不是失败**。
"""

import os

import pytest

#: 集成测试总开关。
INTEGRATION_ENABLED = bool(os.environ.get("ZHIKU_INTEGRATION", "").strip())

SKIP_REASON = "需要安装 torch 的完整环境，设置 ZHIKU_INTEGRATION=1 后启用"


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason=SKIP_REASON)
def test_torch_importable_and_reports_version():
    """PyTorch 可被导入且能读到版本号。"""
    torch = pytest.importorskip("torch", reason="未安装 torch，跳过 CUDA 相关测试")

    assert torch.__version__, "torch.__version__ 为空"


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason=SKIP_REASON)
def test_cuda_availability_is_queryable():
    """CUDA 可用性与设备数可被查询（CPU 版返回 False / 0 属正常）。"""
    torch = pytest.importorskip("torch", reason="未安装 torch，跳过 CUDA 相关测试")

    is_available = torch.cuda.is_available()
    assert isinstance(is_available, bool)

    device_count = torch.cuda.device_count()
    assert isinstance(device_count, int)
    assert device_count >= 0

    # CPU 版：is_available 为 False 时设备数必须为 0，二者不应自相矛盾
    if not is_available:
        assert device_count == 0


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason=SKIP_REASON)
def test_cuda_device_name_when_gpu_present():
    """存在 GPU 时应能读到 0 号设备名称；无 GPU 则跳过。"""
    torch = pytest.importorskip("torch", reason="未安装 torch，跳过 CUDA 相关测试")

    if not torch.cuda.is_available():
        pytest.skip("当前机器无可用 CUDA 设备（CPU 版环境属正常情况）")

    device_name = torch.cuda.get_device_name(0)
    assert device_name, "CUDA 设备名称为空"
