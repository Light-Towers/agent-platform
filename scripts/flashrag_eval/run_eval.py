"""用 FlashRAG 的 retrieval_recall@k 指标，对照「关 rerank」与「开 rerank」的检索准确率。

用法：
    # 关 rerank
    RERANK_ENABLED=false uv run python scripts/flashrag_eval/run_eval.py
    # 开 rerank
    RERANK_ENABLED=true  uv run python scripts/flashrag_eval/run_eval.py

两次分别得到 retrieval_recall_top{k}，差值 Δ 即为 rerank 带来的准确率变化。
rerank 开关完全由 .env / 环境变量 RERANK_ENABLED 控制，脚本本身不改检索逻辑。

黄金集（business_golden）：用 agent 自身 pg/kafka/redis 三篇文档构造，
每条含 question + golden_answers（正确答案短语），retrieval_recall 度量
top-k 文档里是否包含能回答问题的内容（子串匹配）。
"""

import asyncio
import os
import sys

# 让脚本能 import app
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from agent_retriever import AgentRetriever
from flashrag.config import Config
from flashrag.dataset import Dataset
from flashrag.evaluator import Evaluator

# ---- 评测语料：多段 markdown，每个 ## 主题会被 split_markdown 切成独立 chunk ----
# 这样语料粒度足够细，rerank 才有「把正确 chunk 顶到前面」的发挥空间。
EVAL_DOCS = {
    "pg.md": """# PostgreSQL & pgvector

## pgvector 向量类型与存储
pgvector 提供 vector 类型，用于在 PostgreSQL 中存储向量的列。向量检索通过余弦距离、内积或 L2 距离完成，vector_dim 决定维度，embedding 模型输出决定具体值。

## pgvector 索引类型
pgvector 支持两种索引：ivfflat 和 hnsw。ivfflat 适合静态数据集，hnsw 支持增量写入且召回更高。创建索引时必须指定距离度量函数（如 cosine / L2 / ip）。

## pgvector 与 RAG 集成
在 RAG 流水线中，pgvector 负责语义召回，配合 BM25 做混合检索，再用 rerank 模型重排 top-K。向量维度需与 embedding 模型对齐，BAAI/bge-m3 输出 1024 维。

## pgvector 性能调优
合理设置 ivfflat.probes 或 hnsw 的 ef_search 能平衡召回率与延迟。批量写入前建表、使用 COPY 比逐条 INSERT 快一个数量级。""",
    "kafka.md": """# Apache Kafka

## Kafka 分区与消费者组
Kafka 通过分区（partition）实现水平扩展，同一消费者组（consumer group）内每个分区只被一个消费者消费，不同组之间广播。分区数决定最大并行度。

## Kafka 消息可靠性
Kafka 用 acks 参数控制生产者确认：acks=all 时需所有 ISR 副本写入才算成功，配合 min.insync.replicas 可防止消息丢失。副本（replica）机制保障高可用。

## Kafka 在流处理中的角色
Kafka 是分布式消息队列与流处理中枢，承接日志、事件、变更数据捕获（CDC）。常与 Flink、Spark Streaming 配合做实时计算，是流式架构的骨干。

## Kafka 与 Redis 的分工
Kafka 负责可靠传输与重放，Redis 负责低延迟缓存与实时读写。典型架构：写入经 Kafka 入湖，热数据缓存到 Redis，查询走 Redis 或 pgvector。""",
    "redis.md": """# Redis

## Redis zset 有序集合
Redis 的 zset（有序集合）为每个成员维护一个 score，支持按分数排序与范围查询，常用于排行榜、延迟队列、优先级任务。ZADD / ZRANGEBYSCORE 是核心命令。

## Redis 持久化机制
Redis 提供两种持久化：RDB 快照（紧凑、恢复快、可能丢最后一次快照后的数据）与 AOF 日志（每条写命令追加，更耐久但文件大）。可两者同时开启。

## Redis 作为缓存
Redis 是内存级缓存，支撑高并发低延迟读取。缓存击穿、穿透、雪崩是三大经典问题，可用布隆过滤器、随机过期、互斥锁缓解。

## Redis 与向量检索对比
Redis 原生非向量数据库，但 Redis Stack 提供向量索引。相比 pgvector，Redis 更适合实时特征与缓存，pgvector 更适合与关系数据共存的语义召回。""",
    # ---- 干扰文档：主题相近，制造近义竞争，让 rerank 有重排空间 ----
    "mysql.md": """# MySQL

## MySQL 复制与高可用
MySQL 通过主从复制（replication）实现高可用，binlog 记录变更，从库重放。半同步复制可减少数据丢失，副本（replica）机制保障容灾。

## MySQL 持久化与事务
MySQL 的 InnoDB 通过 redo log 与 double write 保证持久化，事务满足 ACID。相比 Redis 的 RDB/AOF，MySQL 的持久化更偏向关系一致性与崩溃恢复。

## MySQL 索引结构
MySQL 的 B+Tree 索引适合范围查询与排序，与 pgvector 的 ivfflat/hnsw 向量索引不同，B+Tree 不擅长高维语义召回。""",
    "elasticsearch.md": """# Elasticsearch

## Elasticsearch 向量检索
Elasticsearch 自 8.x 起原生支持 dense_vector 字段与向量检索，配合 HNSW 近似最近邻（ANN）做语义召回，是 pgvector 的替代方案之一。

## Elasticsearch 倒排索引
Elasticsearch 以倒排索引（inverted index）为核心，擅长全文检索与 BM25 打分，常与向量召回混合构建 RAG 检索层。

## Elasticsearch 与 Kafka 集成
Elasticsearch 常用 Kafka Connect 消费变更数据（CDC）构建搜索索引，Kafka 负责可靠传输，Elasticsearch 负责检索服务。""",
    "rabbitmq.md": """# RabbitMQ

## RabbitMQ 消息模型
RabbitMQ 基于交换机（exchange）与队列（queue）路由消息，消费者（consumer）从队列拉取。与 Kafka 的分区消费者组模型不同，RabbitMQ 更偏向任务分发与 RPC。

## RabbitMQ 可靠性
RabbitMQ 通过消息确认（ack）、持久化队列与镜像队列保障可靠投递，避免消息丢失。acks 机制与 Kafka 的 acks 参数理念相似但实现不同。

## RabbitMQ 在流处理中的定位
RabbitMQ 更适合企业集成与任务队列，Kafka 更适合高吞吐日志流处理。两者都是消息中间件，但 Kafka 更适合 pgvector 之外的事件中枢。""",
}

# ---- 业务黄金集：问题 + 正确答案短语（在对应 chunk 内容中应能子串命中） ----
BUSINESS_GOLDEN = [
    {
        "question": "pgvector 怎么做向量检索？",
        "golden_answers": ["vector 类型", "存储向量的列"],
    },
    {
        "question": "pgvector 索引支持哪些类型？",
        "golden_answers": ["ivfflat", "hnsw"],
    },
    {
        "question": "Kafka 的分区消费模型是怎样的？",
        "golden_answers": ["分区", "消费者组", "partition"],
    },
    {
        "question": "Kafka 怎么保证消息不丢？",
        "golden_answers": ["ISR 副本", "acks=all"],
    },
    {
        "question": "Redis 的 zset 有什么用？",
        "golden_answers": ["有序集合", "score", "排行榜"],
    },
    {
        "question": "Redis 持久化有哪几种方式？",
        "golden_answers": ["RDB 快照", "AOF 日志"],
    },
    {
        "question": "pgvector 的向量维度怎么定？",
        "golden_answers": ["vector_dim", "1024 维"],
    },
    {
        "question": "Kafka 和 Redis 在架构里各负责什么？",
        "golden_answers": ["Kafka 负责可靠传输", "Redis 负责低延迟缓存"],
    },
]


def build_dataset() -> Dataset:
    items = [
        {"question": g["question"], "golden_answers": g["golden_answers"]}
        for g in BUSINESS_GOLDEN
    ]
    return Dataset(data=items)


async def main():
    from app.config import get_settings
    from app.infra.db import ensure_schema, init_pool
    from app.rag.chunker import split_markdown
    from app.rag.store import add_document

    rerank_on = get_settings().rerank_effective_enabled
    print(f"[eval] rerank_effective_enabled={rerank_on}")

    pool = await init_pool()
    # 评测环境：chunks 为临时入库数据，强制重建以兼容 schema 演进
    # （如远程合并新增 workspace_id 列后，旧 chunks 表缺列会导致 ensure_schema 失败）。
    async with pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS chunks")
        await conn.commit()
    await ensure_schema(pool)

    # 清空历史 chunks（评测环境可丢，避免重复入库污染语料）
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM chunks")
        await conn.commit()

    # 用内置多段评测语料（每个 ## 主题切成独立 chunk，粒度够细以体现 rerank 增益）
    DOCS = EVAL_DOCS
    for src, md in DOCS.items():
        chunks = split_markdown(md)
        await add_document(pool, src, chunks)
        print(f"[ingest] {src}: {len(chunks)} chunks")

    dataset = build_dataset()

    config_dict = {
        "retrieval_method": "agent",
        "metrics": ["retrieval_recall", "retrieval_precision"],
        # FlashRAG 的 retrieval_recall 仅支持单个 int topk（不支持 list）
        "metric_setting": {
            "retrieval_recall_topk": int(os.environ.get("RECALL_TOPK", "5")),
            "retrieval_precision_topk": int(os.environ.get("RECALL_TOPK", "5")),
        },
        "save_dir": os.path.join(ROOT, "scripts", "flashrag_eval", "out"),
        "save_intermediate_data": False,
        "save_metric_score": True,
    }
    config = Config(config_dict=config_dict)

    retriever = AgentRetriever(config, pool=pool)
    # 逐条检索并写回 retrieval_result
    for item in dataset:
        docs = retriever.search(item.question, num=5, return_score=False)
        item.retrieval_result = docs
        # 调试：打印 top-5 来源，便于肉眼看 rerank 是否把正确文档顶到前面
        top_srcs = [d.get("title") or d.get("id") for d in docs]
        print(f"  [retrieve] Q='{item.question}' -> {top_srcs}")

    evaluator = Evaluator(config)
    result_dict = evaluator.evaluate(dataset)
    topk = int(os.environ.get("RECALL_TOPK", "5"))
    print(f"[eval] rerank={rerank_on} topk={topk} 聚合指标: {result_dict}")

    # 逐条分数：优先读 FlashRAG 回填的 item.output["metric_score"]，
    # 若为空（部分 FlashRAG 版本不回填单条），按 golden_answers 子串命中自行判定。
    def _hit(item, topk_n):
        docs = getattr(item, "retrieval_result", None) or []
        docs = docs[:topk_n]
        gold = item.golden_answers or []
        for d in docs:
            text = (d.get("contents") or "") + " " + (d.get("title") or "")
            if any(str(g) in text for g in gold):
                return 1.0
        return 0.0

    print(f"[eval] rerank={rerank_on} 逐条:")
    hit_count = 0
    for item in dataset:
        sc = (getattr(item, "output", None) or {}).get("metric_score", {})
        rk = sc.get(f"retrieval_recall_top{topk}")
        pk = sc.get(f"retrieval_precision_top{topk}")
        if rk is None:  # 回退：自行判定 recall（命中任一条 golden）
            rk = _hit(item, topk)
            pk = None
            if rk:
                hit_count += 1
        else:
            if rk:
                hit_count += 1
        print(f"  Q: {item.question}")
        print(f"     recall@{topk}={rk} precision@{topk}={pk}")


if __name__ == "__main__":
    asyncio.run(main())
