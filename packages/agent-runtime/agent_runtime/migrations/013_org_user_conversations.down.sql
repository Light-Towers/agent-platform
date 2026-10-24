-- v13 回滚：删三级归属实体表。
-- 注意：conversations 删后归属断言消失（thread 回到无归属态），业务数据在
-- checkpoints/业务表不受影响。organizations/users/conversations 均为本迁移新建，
-- 无既有数据可丢。幂等（IF EXISTS）。

DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS organizations;
