from app.lm._logging import logger
from app.conf.embedding_config import embedding_config

# 模型单例对象，避免重复初始化
_bge_m3_ef = None
# api 模式客户端单例（懒初始化；api 路径不 import pymilvus.model，裸 venv 可跑）
_api_embedding_client = None


class _ApiModeEmbeddingStub:
    """
    api 模式下 get_bge_m3_ef() 的占位实例。

    业务节点 node_bge_embedding.step_2_init_model 仅校验模型实例非 None，
    实际向量生成走 generate_embeddings（内部按 EMBEDDING_MODE=api 分发到硅基流动 API），
    因此 api 模式返回占位实例即可，避免加载本地模型 / 依赖 pymilvus.model。
    """


def get_bge_m3_ef():
    """
    获取BGE-M3模型单例对象，自动加载环境变量配置。

    M8 扩展：EMBEDDING_MODE=api 时不加载本地模型，返回占位实例
    （业务节点仅校验非 None；真实向量由 generate_embeddings 走硅基流动 API）。
    local 模式行为与 M7 及之前完全一致。
    :return: 初始化完成的BGEM3EmbeddingFunction实例；api 模式返回占位实例
    """
    global _bge_m3_ef
    # M8：api 模式 —— 不初始化本地模型，返回占位实例
    if embedding_config.embedding_mode == "api":
        logger.info("EMBEDDING_MODE=api：返回占位实例，稠密向量走硅基流动 API、稀疏向量本地生成")
        return _ApiModeEmbeddingStub()

    # 单例模式：已初始化则直接返回，避免重复加载模型
    if _bge_m3_ef is not None:
        logger.debug("BGE-M3模型单例已存在，直接返回实例")
        return _bge_m3_ef

    # 从环境变量加载配置，无配置则使用默认值
    # 本地有可以使用本地地址！ 没有使用 "BAAI/bge-m3" 会自动下载！ 如果云端部署也可以使用url地址！
    model_name = embedding_config.bge_m3_path or "BAAI/bge-m3"
    device = embedding_config.bge_device or "cpu"
    use_fp16 = embedding_config.bge_fp16 or False

    # 打印模型初始化配置，便于问题排查
    logger.info(
        "开始初始化BGE-M3模型",
        extra={"model_name": model_name, "device": device, "use_fp16": use_fp16, "normalize_embeddings": True},
    )

    try:
        # 懒导入：仅在 local 模式需要时引入 pymilvus.model（api 模式裸 venv 可跑）
        from pymilvus.model.hybrid import BGEM3EmbeddingFunction

        # 初始化BGE-M3模型，开启原生L2归一化（适配Milvus IP内积检索）
        _bge_m3_ef = BGEM3EmbeddingFunction(
            model_name=model_name,
            device=device,
            use_fp16=use_fp16,
            normalize_embeddings=True,  # 模型原生对稠密+稀疏向量做L2归一化
        )
        logger.success("BGE-M3模型初始化成功，已开启原生L2归一化")
        return _bge_m3_ef
    except Exception as e:
        logger.error(f"BGE-M3模型初始化失败：{str(e)}", exc_info=True)
        raise  # 向上抛出异常，由调用方处理


def _get_api_embedding_client():
    """获取硅基流动 embedding 客户端单例（M8，懒初始化，仅 api 模式调用）。"""
    global _api_embedding_client
    if _api_embedding_client is None:
        if not embedding_config.siliconflow_api_key:
            raise RuntimeError("EMBEDDING_MODE=api 但 SILICONFLOW_API_KEY 未配置")
        from app.lm.siliconflow_client import SiliconFlowEmbeddingClient

        _api_embedding_client = SiliconFlowEmbeddingClient(
            api_key=embedding_config.siliconflow_api_key,
            base_url=embedding_config.siliconflow_base_url,
            model=embedding_config.siliconflow_embedding_model,
        )
    return _api_embedding_client


def _generate_embeddings_api(texts):
    """
    api 模式向量生成：稠密走硅基流动 API（本地 L2 归一化），稀疏本地生成（B 路线）。

    返回结构与 local 模式完全一致：{"dense": [[...], ...], "sparse": [{id: w, ...}, ...]}
    → 业务节点零改动。
    """
    from app.lm.sparse_vectorizer import build_sparse_vectors

    client = _get_api_embedding_client()
    dense = client.embed(texts)  # 已做本地 L2 归一化，与 local 模式 BGE-M3 产物语义对齐
    sparse = build_sparse_vectors(texts)  # 与稠密同一拼接文本，保证 doc/query token 空间一致
    logger.success(f"api 模式：{len(texts)}条文本向量生成完成（稠密API + 稀疏本地）")
    return {"dense": dense, "sparse": sparse}


def _generate_embeddings_local(texts):
    """local 模式向量生成（M7 及之前的原始实现，行为完全一致）。"""
    # 加载BGE-M3模型单例
    model = get_bge_m3_ef()
    # 模型编码生成向量，返回dense（稠密向量）+sparse（CSR格式稀疏向量）
    embeddings = model.encode_documents(texts)
    logger.debug(f"模型编码完成，开始解析稀疏向量格式，共{len(texts)}条")

    # 初始化稀疏向量处理结果，解析为字典格式（适配序列化/存储）
    processed_sparse = []
    for i in range(len(texts)):
        # 提取第i个文本的稀疏向量索引：np.int64 → Python int（满足字典key可哈希要求）
        sparse_indices = (
            embeddings["sparse"].indices[embeddings["sparse"].indptr[i] : embeddings["sparse"].indptr[i + 1]].tolist()
        )
        # 提取第i个文本的稀疏向量权重：np.float32 → Python float（适配JSON序列化/接口返回）
        sparse_data = (
            embeddings["sparse"].data[embeddings["sparse"].indptr[i] : embeddings["sparse"].indptr[i + 1]].tolist()
        )
        # 构造{特征索引: 归一化权重}的稀疏向量字典
        sparse_dict = {k: v for k, v in zip(sparse_indices, sparse_data)}
        processed_sparse.append(sparse_dict)

    # 构造最终返回结果，稠密向量转列表（解决numpy数组不可序列化问题）
    result = {
        "dense": [emb.tolist() for emb in embeddings["dense"]],  # 嵌套列表，与输入文本一一对应
        "sparse": processed_sparse,  # 字典列表，模型已做L2归一化
    }
    logger.success(f"{len(texts)}条文本向量生成完成，格式已适配工业级使用")
    return result


def generate_embeddings(texts):
    """
    为文本列表生成稠密+稀疏混合向量嵌入（模型原生L2归一化）。

    M8 扩展：EMBEDDING_MODE=api 时稠密走硅基流动 API（本地 L2 归一化）、
    稀疏由 app/lm/sparse_vectorizer.py 本地生成（B 路线）；返回结构与 local 完全一致。
    :param texts: 要生成嵌入的文本列表，单文本也需封装为列表
    :return: 字典格式的向量结果，key为dense/sparse，对应嵌套列表/字典列表
    :raise: 向量生成过程中的异常，由调用方捕获处理
    """
    # 入参合法性校验
    if not isinstance(texts, list) or len(texts) == 0:
        logger.warning("生成向量入参不合法，texts必须为非空列表")
        raise ValueError("参数texts必须是包含文本的非空列表")

    logger.info(f"开始为{len(texts)}条文本生成混合向量嵌入")
    try:
        # M8：按模式分发；未知值回退 local（向后兼容铁律）
        mode = embedding_config.embedding_mode
        if mode == "api":
            return _generate_embeddings_api(texts)
        if mode not in ("", "local"):
            logger.warning(f"EMBEDDING_MODE 未知值 '{mode}'，回退 local 模式")

        return _generate_embeddings_local(texts)
    except Exception as e:
        logger.error("文本向量生成失败：{}", e, exc_info=True)
        raise  # 不吞异常，向上传递让调用方做重试/降级处理


"""
核心设计亮点&适配说明：
1. 模型原生归一化：开启normalize_embeddings = True，自动对稠密+稀疏向量做L2归一化，完美适配Milvus IP内积检索（单位化后IP等价于余弦，计算更快）；
2. 彻底解决NumPy类型做key问题：sparse_indices加.tolist()，将np.int64转为Python原生int，满足字典key的可哈希要求，无报错风险；
3. 稀疏值适配序列化：sparse_data加.tolist()，将np.float32转为Python原生float，支持JSON写入/接口返回/Milvus入库等所有场景；
4. 单例模式优化：模型仅初始化一次，避免重复加载耗时耗资源，提升批量处理效率；
5. 格式匹配业务调用：返回dense嵌套列表、sparse字典列表，与vector_result["dense"][0]/sparse_vector["sparse"][0]取值逻辑完美契合；
6. 分级日志覆盖：从模型初始化、向量生成到异常报错，全流程日志记录，便于生产环境问题排查；
7. 入参合法性校验：防止空列表/非列表入参导致的内部报错，提升工具类健壮性。
M8 扩展说明：
8. 双模式分发：EMBEDDING_MODE=local（默认）走本地 BGE-M3（行为与之前完全一致）；=api 走硅基流动
   embeddings API（稠密）+ sparse_vectorizer 本地稀疏（B 路线），无 GPU / 无本地模型也可完整跑通；
9. api 路径懒导入：pymilvus.model 仅在 local 模式 get_bge_m3_ef 内部导入，api 模式裸 venv 可运行。
"""
