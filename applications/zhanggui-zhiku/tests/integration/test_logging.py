# -*- coding: utf-8 -*-
"""
loguru 日志器各级别输出与异常捕获验证。

归并自：`test/02-日志测试.py`（原为逐级别打日志的手测脚本）。

原脚本按 TRACE / DEBUG / INFO / SUCCESS / WARNING / ERROR / CRITICAL 七个级别
各打若干条日志，并用 `@logger.catch` 演示异常自动捕获。这里保留全部日志内容与
调用方式，仅补上「调用不抛异常」「@logger.catch 吞掉除零异常并返回 None」两条断言。

依赖：`app.core.logger`（间接依赖 loguru + app.core.config）。
loguru 是 pyproject 声明的运行时依赖，但为避免在**未装依赖的裸环境**下收集期
ImportError，import 一律放在函数体内，并配合 `importorskip` 守卫。
"""

import pytest


def test_logger_all_levels_emit_without_error():
    """七个日志级别逐一调用，均不应抛异常。"""
    pytest.importorskip("loguru", reason="缺少 loguru，跳过日志测试")
    from app.core.logger import logger

    # --- 1. TRACE (最详细) ---
    # 场景：极其详细的内部流程追踪，通常用于调试复杂的算法或状态机
    logger.trace("进入函数 calculate_complex_logic，参数 x=10, y=20")
    logger.trace("中间变量 state={'step': 1, 'val': 30}")

    # --- 2. DEBUG (调试) ---
    # 场景：开发阶段的调试信息，变量值，函数入口出口
    logger.debug("数据库连接池当前大小：5")
    logger.debug("正在尝试重试第 2 次请求...")

    # --- 3. INFO (信息) ---
    # 场景：正常的业务流程关键节点，用户操作，系统启动/停止
    logger.info("用户 ID: 1001 登录成功")
    logger.info("订单 #9527 已创建，金额：¥299.00")
    logger.info("系统健康检查通过")

    # --- 4. SUCCESS (成功 - Loguru 特有) ---
    # 场景：明确标记某个耗时操作或关键任务圆满完成
    logger.success("数据备份完成！文件已保存至 /backup/2026-03-15.zip")
    logger.success("模型训练结束，准确率达到 98.5%")

    # --- 5. WARNING (警告) ---
    # 场景：非致命错误，使用了废弃 API，配置项缺失使用默认值，重试前的提示
    logger.warning("配置文件缺少 'TIMEOUT' 字段，使用默认值 30s")
    logger.warning("检测到 API 响应时间超过 2s，性能可能下降")
    logger.warning("用户密码强度较弱，建议修改")

    # --- 6. ERROR (错误) ---
    # 场景：操作失败，但程序仍可继续运行（如单个请求失败，文件写入失败）
    logger.error("无法连接到 Redis 服务器：Connection refused")
    logger.error("用户 ID: 1002 的数据解析失败，跳过该记录")

    # --- 7. CRITICAL (严重) ---
    # 场景：致命错误，程序无法继续运行，即将崩溃或退出
    logger.critical("磁盘空间已满！无法写入任何新数据，系统即将停止服务")
    logger.critical("核心加密密钥丢失，安全模块初始化失败")


def test_logger_catch_swallows_exception_and_returns_none():
    """`@logger.catch` 装饰的函数发生异常时应被记录并返回 None，而非向上抛出。"""
    pytest.importorskip("loguru", reason="缺少 loguru，跳过日志测试")
    from app.core.logger import logger

    @logger.catch
    def divide(a: float, b: float) -> float:
        return a / b

    # 正常路径
    assert divide(10, 2) == 5

    # 异常路径：logger.catch 默认 reraise=False，异常被记录为 ERROR 后返回 None
    assert divide(10, 0) is None
