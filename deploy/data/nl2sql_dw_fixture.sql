-- nl2sql 问数样例数仓（nl2sql_dw）的**结构与数据**单一真相源。
--
-- 为什么需要这个文件：golden/seed_dw.sql 只有 INSERT、不含 CREATE TABLE——表当初是
-- 手工建在临时容器里的（容器已灭），于是"重置数据"有仓内依据、"建表"没有，
-- 新环境无法从零重放。本文件补的就是这一半：schema + 注释 + 初始数据。
-- 三方分工（批次 2 的三库三角色，见 deploy/k8s/35-nl2sql-dbsql-job.yaml）：
--   * 本文件 = dw 侧 schema + 数据 + 注释，由 Job 以 dw_owner 身份执行（SET ROLE）；
--   * golden/seed_dw.sql = 仅重置数据（TRUNCATE + 重插），前置条件是本文件已建表；
--   * 服务账号 nl2sql_dw_reader 只有 GRANT SELECT（L1 纵深），本文件不含任何 GRANT。
--
-- 基线事实与 seed_dw.sql / golden/nl2sql_golden.jsonl 的注释逐值对齐
-- （2026-10-19 固化；改这里的数据必须同步改那两处的期望值，否则门禁自证失效）：
--   * 已支付 4 笔、合计 388.50（orders id 1/3/4/6）——golden g10/g20
--   * 已退款 1 行 80.00（id 2）——golden g02/g03/g32
--   * 待支付 1 行 999.99（id 5，user 3 王五）——golden g22/g51（金额最大）
--   * 用户城市：北京 2（users 1/3）、上海 1、广州 1；订单按城市 北京 4/上海 1/广州 1——g13
--   * created_at 跨 2026-09（3 单）与 2026-10（3 单），**无 8 月**——g40/g41/g42
--     （8 月为空是 genuinely_empty 判别用例的根基，别"顺手补一行 8 月数据"）
--   * 全 6 单合计 1468.49、均值 244.75——g21
--
-- 类型口径要如实：nl2sql_meta_config.yaml 的 data_type 必须等于本库
-- information_schema.columns.data_type 的**原样拼写**（character varying /
-- timestamp without time zone / numeric / bigint），否则 scripts/detect_drift 每次
-- 都报一批假的 type_changed。城市与状态用 varchar 而非 text，是刻意的：
-- services/value_resolver.py 的 LinkablePolicy 把 `text` 列入 _DENY_TYPES，
-- 声明成 text 会让取值只读探针（validate_literals 的唯一源侧判据）永久降级 unknown。
--
-- 幂等：CREATE IF NOT EXISTS + TRUNCATE CASCADE 重插 + setval 回拨序列，可重复执行。

CREATE TABLE IF NOT EXISTS users (
    id    bigserial PRIMARY KEY,
    name  varchar(64) NOT NULL,
    phone varchar(20),
    city  varchar(32)
);

CREATE TABLE IF NOT EXISTS orders (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (id),
    status     varchar(16) NOT NULL,
    amount     numeric(12, 2) NOT NULL,
    created_at timestamp NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at);

-- 表/列注释：元知识读路径的真口径来源（dw_repository.list_tables 走 obj_description，
-- 而 nl2sql_meta_config.yaml 的 column_comment 与本段必须**逐字同词**——两处不一致时
-- 生成期 prompt 里会出现两套口径，模型按哪套答都无法判定。这条不靠人记：
-- tests/test_meta_deployment_config.py 直接比对两边的 comment 字符串（改一侧不同步改另一侧就红）。
COMMENT ON TABLE users IS '用户表：一行一个下单用户，收货城市即订单归属城市';
COMMENT ON COLUMN users.id IS '用户ID（主键，orders.user_id 指向它）';
COMMENT ON COLUMN users.name IS '用户姓名';
COMMENT ON COLUMN users.phone IS '手机号（敏感列：L2 投影黑名单 + L3 结果掩码的靶子，值不得出现在响应里）';
COMMENT ON COLUMN users.city IS '收货城市，低基数枚举（北京/上海/广州），取值探针的 linkable 列';

COMMENT ON TABLE orders IS '订单表：一行一笔订单，金额与状态是问数主口径';
COMMENT ON COLUMN orders.id IS '订单ID（主键）';
COMMENT ON COLUMN orders.user_id IS '下单用户ID（外键 -> users.id）';
COMMENT ON COLUMN orders.status IS '订单状态中文枚举：已支付 / 已退款 / 待支付';
COMMENT ON COLUMN orders.amount IS '订单金额（元，两位小数）';
COMMENT ON COLUMN orders.created_at IS '下单时间（无时区）；真列名是 created_at，不是 create_time';

TRUNCATE orders, users RESTART IDENTITY CASCADE;

INSERT INTO users (id, name, phone, city) VALUES
    (1, '张三', '13812345678', '北京'),
    (2, '李四', '13987654321', '上海'),
    (3, '王五', '13700001111', '北京'),
    (4, '赵六', '13655556666', '广州');

INSERT INTO orders (id, user_id, status, amount, created_at) VALUES
    (1, 1, '已支付', 120.50, '2026-09-05'),
    (2, 1, '已退款', 80.00, '2026-09-12'),
    (3, 2, '已支付', 200.00, '2026-09-20'),
    (4, 3, '已支付', 55.00, '2026-10-02'),
    (5, 3, '待支付', 999.99, '2026-10-08'),
    (6, 4, '已支付', 13.00, '2026-10-11');

-- 显式插 id 后 bigserial 序列仍停在 1：不回拨，下一个真实插入会撞主键
-- （RESTART IDENTITY 只重置序列、INSERT 显式值又把它推回去，两者不是一回事）。
SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users));
SELECT setval(pg_get_serial_sequence('orders', 'id'), (SELECT MAX(id) FROM orders));
