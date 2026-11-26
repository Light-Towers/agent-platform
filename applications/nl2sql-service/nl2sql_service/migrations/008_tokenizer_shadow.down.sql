-- 回滚 ADR-0017/T9 影子列；正式 search_text / tokenizer 不受影响。
DROP INDEX IF EXISTS idx_nl2sql_value_info_tsvector_shadow;
ALTER TABLE nl2sql_value_info DROP COLUMN IF EXISTS value_tsvector_shadow;
ALTER TABLE nl2sql_value_info DROP COLUMN IF EXISTS tokenizer_shadow;
ALTER TABLE nl2sql_value_info DROP COLUMN IF EXISTS search_text_shadow;
