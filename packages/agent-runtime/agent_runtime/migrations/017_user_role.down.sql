-- v17 回滚：摘掉 017 加的 role 列与值域约束。
-- 可逆性说明：role 列可丢——目录回退到 is_admin 单位（013/016 的形状）；
-- 但**已发出的带 role claim 的 JWT 不会因此失效**（令牌无状态），旧镜像消费侧
-- 对未知 claim 的处理是忽略（verify_token 只取白名单键）。

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_domain;
ALTER TABLE users DROP COLUMN IF EXISTS role;
