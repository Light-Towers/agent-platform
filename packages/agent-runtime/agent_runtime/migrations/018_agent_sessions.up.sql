-- v18: 多会话目录（服务端签发 session_id + 归属断言 + 派生 thread 映射）
--
-- 背景：D-l 安全红线下，认证模式的 thread_id 由服务端断言主体派生、客户端值被忽略
-- （防会话劫持），天然"一人一会话"。要支持多会话窗口，另立**旁置目录表**：
--   · session_id 由服务端签发（uuid4 hex），前端只持有它；
--   · thread_id = 断言主体派生值 + 会话后缀（本表只存映射，不让客户端指定）；
--   · 归属用 (org_id, user_id) 纯字符串断言，读写前校验——不挂 organizations/users
--     外键（JWT 登录用户的 tenant 未必在 organizations 表，挂 FK 会插入失败）。
--
-- 为什么不复用 013 conversations：那张表 org_id 有 FK→organizations，而登录租户
-- 可能未回填进 organizations；且它的主键语义是 thread_id（D11），与这里"session_id
-- 为业务主键 + thread_id 为派生值"的模型不同。旁置新表、互不干扰。
--
-- 幂等：IF NOT EXISTS；不回改已应用文件（checksum 钉住）。

CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id     TEXT PRIMARY KEY,
    org_id         TEXT NOT NULL,
    user_id        TEXT NOT NULL DEFAULT '',
    thread_id      TEXT NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    workspace_id   TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_scope
    ON agent_sessions (org_id, user_id, last_active_at DESC);
