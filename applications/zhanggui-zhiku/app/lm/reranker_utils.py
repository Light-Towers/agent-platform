from app.conf.reranker_config import reranker_config

_reranker_model = None
# api 模式 reranker 单例（懒初始化；api 路径不 import FlagEmbedding，裸 venv 可跑）
_api_reranker = None


def get_reranker_model():
    """
    获取重排序模型实例，按 RERANK_MODE 分发（M8）。

    - RERANK_MODE=api：返回 ApiReranker（与 FlagReranker.compute_score 同签名/同语义），
      内部调用硅基流动 /rerank 接口；不依赖 FlagEmbedding / 本地模型。
    - 默认 local：返回 FlagReranker 本地实例（行为与 M7 及之前完全一致）；
      FlagEmbedding 改为懒导入，避免 api 模式需要安装该依赖。
    """
    global _reranker_model, _api_reranker

    # M8：api 模式 —— 懒初始化 ApiReranker 单例
    if reranker_config.rerank_mode == "api":
        if _api_reranker is None:
            if not reranker_config.siliconflow_api_key:
                raise RuntimeError("RERANK_MODE=api 但 SILICONFLOW_API_KEY 未配置")
            from app.lm.siliconflow_client import ApiReranker

            _api_reranker = ApiReranker(
                api_key=reranker_config.siliconflow_api_key,
                base_url=reranker_config.siliconflow_base_url,
                model=reranker_config.siliconflow_rerank_model,
            )
        return _api_reranker

    # 未知值回退 local（向后兼容铁律）
    if reranker_config.rerank_mode not in ("", "local"):
        from app.lm._logging import logger

        logger.warning(f"RERANK_MODE 未知值 '{reranker_config.rerank_mode}'，回退 local 模式")

    # local 模式：懒导入 FlagEmbedding，行为与之前完全一致
    if _reranker_model is None:
        from FlagEmbedding import FlagReranker

        _reranker_model = FlagReranker(
            model_name_or_path=reranker_config.bge_reranker_large,
            device=reranker_config.bge_reranker_device,
            use_fp16=reranker_config.bge_reranker_fp16,
        )
    return _reranker_model
