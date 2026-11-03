-- nl2sql golden 门禁的 DW 种子（2026-10-19 从首跑基线所用 docker PG 原样固化）。
-- 背景：golden 期望值长期没有仓内真值依据（种子当初手工建于容器，已灭）；
-- 本文件让门禁可复现——跑 run_golden 前先在本库把数据重置成本基线。
--
-- ⚠ 前置（2026-10-27）：本文件**只重置数据、不建表**——它只有 INSERT，表结构
-- 的唯一真相源是仓根的 deploy/data/nl2sql_dw_fixture.sql（CREATE TABLE + 注释 + 初始数据，
-- 由 deploy/k8s/35-nl2sql-dbsql-job.yaml 应用）。新库上先跑 fixture 再跑本文件，
-- 否则本文件第一条 TRUNCATE 就报 relation "orders" does not exist
-- ——那正是"手工建于容器"留下的形状：重置有仓内依据、建表没有。
-- 两个文件的数据是**刻意重复**的（fixture 建新库、seed 重置老库），
-- 由 tests/test_golden_seed_real_pg.py 在两步之后各自复跑同一批聚合读数钉住：
-- 任一侧数值漂出门禁登记的基线，用例就红——重复不是风险，无判据的重复才是。
--
-- 保留的已登记基线事实（baseline-and-ownership.md §5 首跑读数对应本数据）：
--   * 已支付 4 笔、合计 388.50（id 1/3/4/6）
--   * 已退款 1 行（id 2，80.00）
--   * 收货城市：北京（users 1/3）、上海（user 2）、广州（user 4）
--   * created_at 跨 2026-09 / 2026-10 两个月（支撑「上个月」时间窗用例）；
--     无 8 月数据（支撑 genuinely_empty 用例）
-- 注意：真列名是 created_at（首跑 g01 曾幻觉 create_time，见 §5 失败明细）。
-- 幂等：TRUNCATE + RESTART IDENTITY 后重插，可重复执行。

TRUNCATE orders, users RESTART IDENTITY CASCADE;

INSERT INTO users (id, name, phone, city) VALUES
    (1, '张三', '13812345678', '北京'),
    (2, '李四', '13987654321', '上海'),
    (3, '王五', '13700001111', '北京'),
    (4, '赵六', '13655556666', '广州');

INSERT INTO orders (id, user_id, status, amount, created_at) VALUES
    (1, 1, '已支付', 120.50, '2026-09-05'),
    (2, 1, '已退款',  80.00, '2026-09-12'),
    (3, 2, '已支付', 200.00, '2026-09-20'),
    (4, 3, '已支付',  55.00, '2026-10-02'),
    (5, 3, '待支付', 999.99, '2026-10-08'),
    (6, 4, '已支付',  13.00, '2026-10-11');

-- 显式插 id 后 bigserial 序列仍停在 1（RESTART IDENTITY 只把序列归零，不会跟着显式值走）：
-- 不回拨的话，门禁之外第一次真实插入就撞主键。deploy/data/nl2sql_dw_fixture.sql 末段同形。
SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users));
SELECT setval(pg_get_serial_sequence('orders', 'id'), (SELECT MAX(id) FROM orders));
