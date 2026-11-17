-- v19: 会话标题来源标记（治本：标题生命周期 default → auto → manual）
--
-- 背景：v18 的 title 只是创建时写入的字符串，既不能改、也不会随对话内容更新，
-- 更没有「谁有权覆盖谁」的规则。加一列来源标记，把标题变成一个受控状态机：
--   · default —— 创建时的占位文案（如「新会话 …」）；
--   · auto    —— 首轮问答后由 LLM 按对话内容生成（或失败回退的截断问题）；
--   · manual  —— 用户手动改名，锁定，自动生成永不覆盖。
--
-- 写入侧的两条硬约束（在 sessions_service 落 SQL 时保证，不靠这里）：
--   ① 自动生成只在 title_source='default' 时执行，且 UPDATE 带
--      `AND title_source='default'` 的 CAS 条件（判与写之间被手改也不覆盖）；
--   ② 手动改名无条件写 title_source='manual'。
--
-- 幂等：ADD COLUMN IF NOT EXISTS；旧行回填 default。不回改已应用文件（checksum 钉死）。

ALTER TABLE agent_sessions
    ADD COLUMN IF NOT EXISTS title_source TEXT NOT NULL DEFAULT 'default';
