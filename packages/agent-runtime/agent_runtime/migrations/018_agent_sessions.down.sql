-- v18 down: 撤销多会话目录表（只删本表，不碰 013 的 organizations/users/conversations）
DROP TABLE IF EXISTS agent_sessions;
