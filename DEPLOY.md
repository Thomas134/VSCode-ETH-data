# 🚀 部署指南

## 1. 环境要求

- Python **3.10+**
- 磁盘空间：**至少 500MB**（数据库约 230MB）

---

## 2. 快速部署（Replit）

### 2.1 Fork / 导入项目

在 Replit 中：
1. 点击 **"Create Repl"** → **"Import from GitHub"**
2. 输入仓库 URL，导入
3. Replit 会自动检测 `.replit` 文件并配置运行命令

### 2.2 安装依赖

```bash
pip install -r requirements.txt
```

### 2.3 启动

Replit 会自动执行 `.replit` 中配置的命令：

```bash
cd web && gunicorn app:app --bind 0.0.0.0:8080 --workers 2 --timeout 120 --log-level info
```

或者手动运行（开发调试用）：

```bash
cd web && python app.py
```

### 2.4 访问

- Replit 会自动打开 Web 预览窗口
- 主页面：`/`（原始K线图）
- 结构页面：`/structure`（标准化K线图）

---

## 3. 项目结构

```
project-root/
├── bybit_eth_data/data/processed/   # SQLite 数据库（138MB + 92MB）
│   ├── eth_perpetual.db            # 原始K线数据
│   └── eth_structure.db            # 结构K线数据（含分型标记）
├── web/                            # Flask Web 应用
│   ├── app.py                      # 入口文件
│   ├── api/                        # API 模块
│   │   ├── config.py              # 全局配置（数据库路径等）
│   │   ├── kline_api.py           # K线查询 + 分型区间匹配
│   │   ├── structure_api.py       # 结构K线查询 + 叠加
│   │   ├── backtest_api.py        # 回测引擎 API
│   │   └── cache_manager.py       # 缓存管理
│   ├── static/                     # 静态资源
│   │   ├── css/style.css          # Bybit 风格暗色主题
│   │   └── js/
│   │       ├── chart.js           # 原始K线图（主页面）
│   │       ├── structure_chart.js # 结构K线图
│   │       └── utils/validators.js
│   └── templates/
│       ├── index.html             # 主页面
│       └── structure.html         # 结构K线页面
├── backtest/                       # 回测引擎
│   └── engine.py                  # BacktestEngine 类
├── .replit                         # Replit 运行配置
├── requirements.txt                # pip 依赖
└── DEPLOY.md                       # 本文件
```

---

## 4. API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/kline` | GET | 原始K线数据（含分型区间） |
| `/api/structure_kline` | GET | 结构K线数据 |
| `/api/source_kline` | GET | 原始K线（用于叠加显示） |
| `/api/backtest` | POST | 执行回测 |
| `/api/stats` | GET | 原始K线数据统计 |
| `/api/structure_stats` | GET | 结构K线数据统计 |
| `/api/fractals` | GET | 分型数据（用于回测信号） |
| `/api/intervals` | GET | 支持的时间级别列表 |
| `/api/cache/clear` | GET | 清除缓存 |

### K线查询参数

```
GET /api/kline?interval=1m&limit=500&before=1234567890000
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `interval` | string | `1m` | `1m`, `5m`, `15m`, `1h`, `4h`, `1d` |
| `limit` | int | `500` | 最大 2000 |
| `before` | int(ms) | — | 分页：获取此时间戳之前的更早数据 |

---

## 5. 配置

所有配置集中在 `web/api/config.py`：

| 配置项 | 说明 |
|--------|------|
| `DB_PATH` | 原始K线数据库路径 |
| `STRUCTURE_DB` | 结构K线数据库路径 |
| `DEFAULT_LIMIT` | 默认每次加载的K线数量（500） |
| `KLINE_TABLE_MAP` | 时间级别 → K线表名映射 |
| `FRACTAL_TABLE_MAP` | 时间级别 → 分型表名映射 |
| `INTERVAL_MS` | 各时间级别的毫秒数 |

---

## 6. 性能说明

### 6.1 数据库

- **SQLite 只读模式**：API 全部使用 `mode=ro`（只读）连接，不会锁库
- **分页加载**：每次加载 500 根K线，向左滚动自动触发更多加载
- **缓存**：分型匹配结果缓存在内存中，切换时间周期不会重复计算

### 6.2 Gunicorn

- **2 workers**：可在 `.replit` 中调整
- **gzip 压缩**：JSON 响应 > 1KB 自动压缩
- **超时 120s**：回测等长任务不会被提前中断

### 6.3 前端

- **Lightweight Charts**：CDN 加载（需要互联网）
- **1000根K线限制**：为保持性能，分型标记只渲染最近 2000 根

---

## 7. 常见问题

### Q: 数据库文件在哪里？
数据库是 SQLite 文件，位于 `bybit_eth_data/data/processed/`，包含两个文件：
- `eth_perpetual.db` — 原始 1 分钟K线数据
- `eth_structure.db` — 标准化K线（含分型标记）

两个文件总计约 **230MB**，已包含在仓库中。

### Q: 如何修改监听的端口？
编辑 `.replit` 中的 `localPort` 和 `externalPort`，或者在 `app.py` 中修改：

```python
port = int(os.environ.get('PORT', 8080))
```

### Q: Replit 上存储空间够吗？
数据库约 230MB，Replit 免费版提供 1GB 存储空间，完全够用。

### Q: 为什么要在模板里写 `{{ config.DEFAULT_LIMIT }}`？
这是 Flask 的 Jinja2 模板语法，用于将后端的 `DEFAULT_LIMIT` 配置传递到前端 JavaScript 中，保持前后端一致。该值在 `web/api/config.py` 中配置。

---

## 8. 技术栈

| 组件 | 版本 | 用途 |
|------|------|------|
| Flask | 3.0+ | Python Web 框架 |
| Gunicorn | 21.2+ | WSGI 服务器 |
| SQLite | 内置 | 数据存储 |
| Lightweight Charts | 4.1.0 | K线图渲染（CDN） |
| SheetJS (xlsx) | 0.18.5 | Excel 导出（CDN） |
