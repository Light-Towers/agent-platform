"""agent_server 测试夹具。

独立 pytest session（Makefile test 第 8 个），importlib 模式下与根 tests/conftest.py
不共享。本目录测试自包含；需要 env 隔离时再在此补 clean_env fixture。
"""
