-- v16 回滚：摘掉 016 加的两列。
-- 可逆性说明：列本身可丢（口令散列不是业务数据，删了等于该账号不能再用口令登录）；
-- 但**已发出的 JWT 不会因此失效**——令牌是无状态 RS256，撤销属 PR-3 的 jti 黑名单面。

ALTER TABLE users DROP COLUMN IF EXISTS last_login_at;
ALTER TABLE users DROP COLUMN IF EXISTS password_hash;
