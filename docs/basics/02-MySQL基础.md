# MySQL 基础

> 类型: 通用基础知识（与项目无关）

面向会用数据库但没系统学过 MySQL 的工程师。目标是把类型选择、索引原理、事务这些"面试常问、工作常错"的内容一次理清。

## 1. 它是什么，适用场景

MySQL 是最流行的开源关系型数据库之一（Oracle 维护，现行主流版本为 8.x）。适合：

- 中小到大型 OLTP（在线事务处理）：订单、用户、内容管理
- 读写均衡、以"结构化记录 + 事务"为核心的系统
- 团队熟悉、云托管支持广泛（RDS 等开箱即用）

不适合：复杂分析（考虑列式库/数仓）、需要丰富数据类型与复杂查询的场景（考虑 PostgreSQL）。

## 2. 安装与连接

```bash
# Ubuntu/Debian
sudo apt install mysql-server

# macOS
brew install mysql && brew services start mysql

# Docker（推荐用于本地开发）
docker run -d --name mysql8 -e MYSQL_ROOT_PASSWORD=123456 -p 3306:3306 mysql:8
```

```bash
# 命令行连接
mysql -h 127.0.0.1 -P 3306 -u root -p
```

```sql
-- 建库并指定字符集（utf8mb4 才能存 emoji，8.0 默认已是 utf8mb4）
CREATE DATABASE shop DEFAULT CHARACTER SET utf8mb4;
SHOW DATABASES;
USE shop;
```

编程语言里用连接池访问（不要每次请求新建连接），例如 Python 的 `PyMySQL` / `mysql-connector-python`，Java 的 HikariCP。

## 3. 库表与常用类型选择

类型选对，一半的性能问题就没了。

| 场景 | 推荐类型 | 说明 |
|---|---|---|
| 主键 | `BIGINT UNSIGNED AUTO_INCREMENT` | 分布式场景再考虑雪花 ID |
| 短字符串 | `VARCHAR(n)` | n 是字符数不是字节数 |
| 定长/枚举值 | `TINYINT` 或 `ENUM` | 一般更推荐 TINYINT + 业务字典 |
| 金额 | `DECIMAL(12,2)` | **绝不用 FLOAT/DOUBLE 存钱** |
| 时间 | `DATETIME` 或 `TIMESTAMP` | TIMESTAMP 带时区转换但只到 2038 年 |
| 大文本 | `TEXT` / `JSON` | 尽量拆表，别塞在主表里 |
| 布尔 | `TINYINT(1)` | MySQL 没有真 BOOLEAN |

建表示例：

```sql
CREATE TABLE users (
  id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name       VARCHAR(64)  NOT NULL,
  email      VARCHAR(128) NOT NULL,
  status     TINYINT      NOT NULL DEFAULT 1 COMMENT '1正常 0禁用',
  balance    DECIMAL(12,2) NOT NULL DEFAULT 0,
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 4. CRUD 与 JOIN 速查

```sql
-- 增
INSERT INTO users (name, email) VALUES ('alice', 'a@x.com');

-- 查（条件、排序、分页）
SELECT id, name FROM users
WHERE status = 1 AND name LIKE 'al%'
ORDER BY id DESC
LIMIT 20 OFFSET 40;

-- 改（一定要带 WHERE！）
UPDATE users SET status = 0 WHERE id = 42;

-- 删（生产环境更常用软删除：加 is_deleted 字段）
DELETE FROM users WHERE id = 42;

-- JOIN：以内连接为主
SELECT o.id, o.amount, u.name
FROM orders o
JOIN users u ON u.id = o.user_id      -- 只留两边都能匹配上的行
LEFT JOIN pay_logs p ON p.order_id = o.id  -- 左表全保留，右表没有则为 NULL
WHERE o.created_at >= '2026-01-01';
```

记忆口诀：`INNER JOIN` 取交集；`LEFT JOIN` 以左表为准；写 JOIN 时必须确保**关联字段上有索引**。

## 5. 索引原理与最左前缀

InnoDB 的索引是 **B+ 树**：一棵矮胖的多叉树，数据都在叶子节点且叶子间有链表相连。

- 3~4 层的 B+ 树即可支撑千万级数据，一次查询只需 3~4 次磁盘 IO
- 主键索引（聚簇索引）的叶子节点存整行数据；二级索引的叶子节点存"主键值"，所以查完二级索引往往还要**回表**查主键
- `EXPLAIN` 中看到 `Using index` 表示覆盖索引（索引里就有需要的列，不用回表），是常见优化手段

### 最左前缀原则

联合索引 `(a, b, c)` 相当于按 a 排序、a 相同再按 b 排序……因此：

```sql
-- 假设有索引 idx_abc(a, b, c)
WHERE a = 1                  -- 能用
WHERE a = 1 AND b = 2        -- 能用
WHERE a = 1 AND b > 2        -- a 等值 + b 范围，可用
WHERE b = 2                  -- 用不上（跳过了 a）
WHERE a = 1 AND c = 3        -- 只用到 a 部分
```

经验法则：

- 等值列放前面，范围列放最后（范围之后的列用不上索引）
- `LIKE 'abc%'` 能用索引，`LIKE '%abc'` 不能
- 对索引列做函数/运算（如 `DATE(created_at) = ...`）通常会让索引失效，改成范围查询 `created_at >= ... AND created_at < ...`
- 区分度低的列（如性别）单独建索引意义不大

## 6. 事务与隔离级别

事务四特性 ACID 中，MySQL 的并发控制核心是 MVCC + 锁。

```sql
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;        -- 或 ROLLBACK
```

四个隔离级别（InnoDB 默认 **REPEATABLE READ**）：

| 级别 | 脏读 | 不可重复读 | 幻读 |
|---|---|---|---|
| READ UNCOMMITTED | 可能 | 可能 | 可能 |
| READ COMMITTED | 不会 | 可能 | 可能 |
| REPEATABLE READ（默认） | 不会 | 不会 | InnoDB 基本避免 |
| SERIALIZABLE | 不会 | 不会 | 不会 |

实用建议：

- 大多数互联网公司实际会调成 `READ COMMITTED`，减少间隙锁带来的死锁
- 事务要**短小**：把耗时操作（外部 HTTP 调用等）移出事务
- `SELECT ... FOR UPDATE` 可以对行加排他锁，用于"读-算-写"的竞态场景

## 7. EXPLAIN 看执行计划

在慢查询前加 `EXPLAIN`（8.0 还可用 `EXPLAIN ANALYZE` 真实执行并给出耗时）：

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 42 ORDER BY created_at DESC LIMIT 10;
```

重点看这几列：

| 列 | 关注点 |
|---|---|
| type | 访问类型。`const`/`eq_ref`/`ref` 好；`range` 可接受；**`ALL` 全表扫描要警惕** |
| key | 实际用到的索引；为 NULL 说明没用上 |
| rows | 预估扫描行数，越少越好 |
| Extra | `Using filesort`（额外排序）、`Using temporary`（临时表）出现时要优化 |

优化套路：先看 type 是不是 ALL → 该加索引加索引 → 再看 rows 是否骤降 → 最后处理 Extra 里的排序/临时表。

## 8. 新手常踩的坑

### 8.1 隐式类型转换

```sql
-- phone 是 VARCHAR，却用数字比较
SELECT * FROM users WHERE phone = 13800000000;
```

字符串列与数字比较时，MySQL 会把**列**转成数字（不是把值转成字符串），导致索引失效、全表扫描，还可能匹配出意外结果。始终让类型保持一致：`WHERE phone = '13800000000'`。

### 8.2 深分页

```sql
LIMIT 1000000, 20   -- 要扫过 100 万行再丢弃，越翻越慢
```

优化：用游标（记住上一页的最后一个 id）：

```sql
SELECT * FROM orders WHERE id < :last_id ORDER BY id DESC LIMIT 20;
```

或先用覆盖索引找出目标主键，再回表关联：

```sql
SELECT o.* FROM orders o
JOIN (SELECT id FROM orders WHERE status = 1 LIMIT 1000000, 20) t ON o.id = t.id;
```

### 8.3 死锁的简单认知

两个事务互相持有对方需要的锁时发生死锁，InnoDB 会自动检测并回滚其中一个（报错 1213）。

- 预防：多个事务**按相同顺序**访问资源；事务尽量短；给热点行的更新加合理索引，避免锁范围被放大（行锁升级成大面积间隙锁）
- 处理：捕获死锁错误后重试即可，这是正常现象不是事故

### 8.4 其他

- `UPDATE`/`DELETE` 忘写 WHERE：开 `sql_safe_updates` 或养成先 `SELECT` 确认的习惯
- `COUNT(*)` vs `COUNT(col)`：前者不忽略 NULL 且通常更快，统计行数用它
- 大表加列/加索引：8.0 的 DDL 多为在线操作，但仍应避开业务高峰

## 9. 一页速查

| 需求 | 关键点 |
|---|---|
| 金额 | `DECIMAL`，禁止浮点 |
| 中文/emoji | `utf8mb4` |
| 联合索引 | 最左前缀，等值在前范围在后 |
| 判断索引是否生效 | `EXPLAIN` 看 type/key/rows |
| 并发扣减 | 事务 + `FOR UPDATE` 或乐观锁 |
| 深分页 | 游标 / 覆盖索引 |
| 死锁 | 统一加锁顺序 + 捕获重试 |

掌握"类型选对 → 索引建对 → EXPLAIN 验证 → 事务写短"这条主线，就能解决 MySQL 日常 80% 的问题。
