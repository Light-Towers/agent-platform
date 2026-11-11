-- v17: users 补 role 列（1a 断言源；方案 docs/plans/plan-roles-kb-datasource-console-2026-11-11.md §5）
-- 依据：ADR-0015（服务端断言 role claim）+ D1（内置三角色，一人一角色）。
--
-- 只加一列 + 一条 CHECK、不回改 013/016（checksum 钉住已应用文件的纪律）：
--   - role NOT NULL DEFAULT 'viewer'：存量行在迁移瞬间取最小权限，等回填语句把 is_admin
--     行收敛成 admin 后即无观感差异；显式默认值使 INSERT 不带 role 也不会炸。
--   - 值域闭合在库层（CHECK），不靠代码约定：签发方拼错码插不进库。
--   - is_admin 列保留不删（F5：契约用例 + 前端已渲染）；语义降级为 role='admin' 的等价物，
--     新代码只读 role，写侧双写（H5：is_admin == (role=='admin')）。
-- 版本号纪律：文件名前缀纯数字 + 下划线（base.py 的 _FILE_PATTERN 只认这个形状）。

ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'viewer';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_domain') THEN
    ALTER TABLE users ADD CONSTRAINT users_role_domain
      CHECK (role IN ('admin','editor','viewer'));
  END IF;
END $$;
-- 回填：原 is_admin 位 → admin；其余由默认值达成（一次性收敛，不双写）
UPDATE users SET role = 'admin' WHERE is_admin AND role = 'viewer';

COMMENT ON COLUMN users.role IS '内置三角色码（admin/editor/viewer，值域由 users_role_domain 闭合）；JWT role claim 与 /auth/me 的断言源（ADR-0015/D1）';
