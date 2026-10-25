-- nl2sql-service 元知识库 schema v3：补 nl2sql_alias_info.updated_at（2026-10-18 E2E 实测发现）
-- 根因：§5.14 加 relation/alias 两表时，relation_info 带了 updated_at 而 alias_info 漏了；
--       MetaRepository._upsert 无条件拼 `updated_at = now()`（其余四表都有该列），于是
--       save_alias 在真 PG 上报 UndefinedColumn——假池单测不校验列存在性，故此前未暴露。
-- 纪律同 001/002：幂等（IF NOT EXISTS）、不回改 001、无数据迁移、不加 DROP。
-- 应用方式同 001：
--   python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"

ALTER TABLE nl2sql_alias_info
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

INSERT INTO nl2sql_schema_meta (key, value) VALUES ('schema_version', '3')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
