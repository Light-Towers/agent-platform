-- v16: users 补凭据列（登录面第一块，方案 docs/plans/plan-web-auth-user-minimal-2026-11-05.md D-a/D-c）
--
-- 只加两列、不回改 013（checksum 钉住已应用文件的纪律，与 015 对 trajectories 的处置同形）：
--   - password_hash **可空**：NULL = 该账号没有口令（存量行 / 将来的机器账号），校验侧一律拒绝。
--     刻意不用 `DEFAULT ''`：空串默认值会造出「任何非空口令都不匹配、而空串口令可过」的窗口
--     （方案 D-c），可空 + fail-closed 没有这个形状。
--   - last_login_at 可空：从未登录成功的账号留 NULL，展示侧不硬造时间。
-- 不另开 username 列 + 唯一索引：013 已定 `id TEXT PRIMARY KEY`，方案 D-d 直接把归一化后的
-- 登录名当 id 用，PK 即唯一性，加列属重复。
-- 版本号纪律：文件名前缀必须是**纯数字 + 下划线**（base.py 的 _FILE_PATTERN 只认这个形状，
-- `014a` 那种字母后缀不会被 discover() 收录，见方案 §9 第一条）。

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

COMMENT ON COLUMN users.password_hash IS 'argon2id 散列（agent_runtime.auth_users.hash_password 产出）；NULL = 无口令账号，校验一律拒（D-c fail-closed）';
COMMENT ON COLUMN users.last_login_at IS '最近一次口令校验成功的时刻；NULL = 从未成功登录';
