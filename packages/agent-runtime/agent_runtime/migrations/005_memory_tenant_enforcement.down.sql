-- v5 rollback: 仅回滚 schema（列默认值恢复 v4 的 ''），刻意不回滚数据。
-- up 的 `''→'default'` 一次性归并在 down 侧不可逆：无法区分回填的 legacy 行与
-- v5 之后新写入的真实 default 桶行，强行 `default→''` 会把后者也抹掉。
-- 安全性由过渡期读谓词兜底：typed.recall 的 tenant 读作用域含 'default' 桶
-- （agent_core/memory/typed.py ``_read_tenant_scope``，Warning#8），回滚后
-- default 租户与新写入（默认值 ''）仍读写一致，无可见性断裂。

ALTER TABLE memories ALTER COLUMN tenant_id SET DEFAULT '';
