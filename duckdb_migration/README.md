# DuckDB 迁移 - 阶段 1

## 文件说明

| 文件 | 说明 |
|------|------|
| `migrate.py` | 主迁移脚本：SQLite → DuckDB |
| `db_factory.py` | DuckDB 连接工厂（供后续阶段替换 `web/api/config.py`） |
| `test_query.py` | 查询兼容性测试：验证现有 SQL 在 DuckDB 中是否正常 |
| `duckdb_data/` | 迁移后的 DuckDB 文件输出目录（运行后生成） |

## 使用步骤

### 1. 安装依赖

```bash
pip install duckdb
```

### 2. 执行迁移

```bash
cd duckdb_migration
python migrate.py
```

输出示例：
```
============================================================
SQLite → DuckDB 迁移工具（阶段 1）
============================================================
...
迁移表: kline_1m ... [OK] 2,345,678 行
...
✓ 验证通过：所有表行数一致

查询性能对比测试
  查询: kline_1m ORDER BY open_time DESC LIMIT 2000
  SQLite:   125.40 ms  (2000 行)
  DuckDB:    45.20 ms  (2000 行)
  DuckDB 快 2.8x
```

### 3. 测试查询兼容性

```bash
python test_query.py
```

验证原项目中所有常用查询模式在 DuckDB 中是否正常执行。

## 阶段 2 准备

当阶段 1 验证无误后，阶段 2 需要：

1. 修改 `web/api/config.py`：
   - 把 `get_db_connection()` 改为返回 DuckDB 连接
   - 把 `get_structure_connection()` 改为返回 DuckDB 连接
2. 修改各 API 文件中的结果集访问方式：
   - SQLite: `row['open_time']`（sqlite3.Row）
   - DuckDB: `row[0]` 或改用 `fetchdf()` 后 `df.open_time`