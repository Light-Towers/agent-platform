-- nl2sql-service 元知识库 schema v7：部署级数据源注册表（G3 刀 3；方案 §5/§6）
--
-- 部署级（P4 拍板）：全企业共享一份数据源清单，不随 tenant/workspace 分片。
-- 字段按方案：id / label / dialect / scope_label / credential_ref(NOT NULL) /
-- is_default / status / updated_by / updated_at。
-- ⚠ 不存任何口令形状：credential_ref 只是 Secret 投影的键名（如 DW_DB_DSN），
--   真实 DSN 由运行时按 ref 从 Secret 投影，库里只落引用名（N1 不进库）。
-- 部分唯一索引保证至多一个默认源（WHERE is_default）。
--
-- 幂等纪律同 001-006：CREATE TABLE IF NOT EXISTS；无 DROP；不回改已应用文件。
-- 应用方式同 001：
--   python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"

CREATE TABLE IF NOT EXISTS nl2sql_datasources (
    id text NOT NULL,
    label text NOT NULL DEFAULT '',
    dialect text NOT NULL DEFAULT 'postgres',
    scope_label text NOT NULL DEFAULT '',
    credential_ref text NOT NULL,
    is_default boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'active',
    updated_by text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_nl2sql_datasources PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_nl2sql_datasources_default
    ON nl2sql_datasources (is_default) WHERE is_default = true;

COMMENT ON COLUMN nl2sql_datasources.credential_ref IS 'Secret 投影键名（如 DW_DB_DSN）；库内只存引用，不存口令';
