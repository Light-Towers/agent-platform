-- v19 down: 撤销标题来源标记列（只删本列，不碰 title 本身）
ALTER TABLE agent_sessions DROP COLUMN IF EXISTS title_source;
