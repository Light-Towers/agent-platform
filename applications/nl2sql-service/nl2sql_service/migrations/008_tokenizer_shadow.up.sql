-- nl2sql-service schema v8（ADR-0017/T9）：取值行分词切换的影子列。
--
-- 为什么：005 的 tokenizer 标记只能识别旧行，不能在重建期间同时用新旧分词服务。
-- 本迁移加影子列，重建脚本先把新分词结果写入影子列；校验通过后在一个事务内
-- 把影子列原子切到正式列。重建期间正式列不动，旧配置继续对外服务，用户无感。
--
-- 纪律同 001-007：幂等、无 DROP（down 文件除外）、不改旧迁移文件。

ALTER TABLE nl2sql_value_info ADD COLUMN IF NOT EXISTS search_text_shadow TEXT NOT NULL DEFAULT '';
ALTER TABLE nl2sql_value_info ADD COLUMN IF NOT EXISTS tokenizer_shadow TEXT NOT NULL DEFAULT '';
ALTER TABLE nl2sql_value_info ADD COLUMN IF NOT EXISTS value_tsvector_shadow tsvector
    GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, coalesce(search_text_shadow, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_nl2sql_value_info_tsvector_shadow
    ON nl2sql_value_info USING gin (value_tsvector_shadow);

COMMENT ON COLUMN nl2sql_value_info.search_text_shadow IS
    'ADR-0017/T9 影子分词文本；校验通过后由 rebuild_tokenizer_shadow.py 原子切到 search_text';
