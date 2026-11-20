# Data Agent · 数据分析研究平台

自然语言驱动的数据查询与分析平台：用户用自然语言提问，平台自动将问题转换为结构化意图查询，经**确定性编译**生成 SQL，在只读数据源上执行并返回结果。

**核心设计原则**：LLM 只负责「理解」（生成结构化意图），编译器（纯代码）负责「精确生成」（意图 → SQL）。将非确定性生成与确定性编译解耦，换取语义正确率与可解释性。

## 核心能力

- **自然语言取数**：中文问题 → 结构化意图 → 方言 SQL → 只读执行 → 结果
- **语义模型**：以 YAML 声明业务字段、度量口径、维度层级、表间关联，作为 SQL 生成的唯一依据
- **确定性编译**：同一意图 + 同一语义模型 = 永远相同的 SQL，正确性由单元测试保证
- **降级路径**：超出语义模型覆盖时由 LLM 直接生成 SQL，并明确标注「未经语义模型校验」
- **自动纠错**：执行失败后分层修复（语法/列名本地修，其余交 LLM），上限 3 次
- **报表看板**：空态配置（不拉业务数据建图）、四种图表、持久看板、维度下钻
- **多轮研究**：围绕主题自动建议下一步、收敛生成摘要、导出 Markdown / Word 报告
- **安全边界**：只读账号 + 只读校验 + 出域白名单（业务数据不进入 LLM）

## 架构

```
自然语言 → [LLM] → 结构化意图(Intent) → [确定性编译器] → SQL → [只读执行] → 结果/图表/摘要
```

模块划分：

| 模块 | 职责 |
|---|---|
| `metadata/` | 数据源连接、表结构采集、敏感对象过滤 |
| `semantic/` | 语义模型 YAML 解析、校验、口径冲突检测 |
| `nl2sql/` | LLM → 结构化意图、降级路径（LLM 直接写 SQL） |
| `compiler/` | 意图 → 方言 SQL（确定性、纯代码） |
| `executor/` | 只读校验、执行、分层自动纠错 |
| `llm/` | LLM 统一适配层 + 出域 sanitizer |
| `l2_agent.py` | Agent 模式：自主决策取数路径（编译/降级/追问/重试） |

## 技术栈

- 后端：Python 3.11+ / FastAPI / SQLAlchemy / sqlglot
- 前端：React + TypeScript + Ant Design + ECharts
- 数据源：MySQL、PostgreSQL（只读账号）
- 元数据库：SQLite（本地）

## 目录结构

```
backend/          FastAPI 后端
  app/            应用源码（metadata / semantic / nl2sql / compiler / executor / llm）
frontend/         React + TS 前端
docker/           样例数据库（MySQL / PostgreSQL，含只读账号与演示数据）
```

## 快速开始

### 1. 启动样例数据库（可选）

内置电商样例库（MySQL），含只读账号与演示数据：

```bash
cd docker
# MySQL 样例库（host 网络，端口 3306）
docker run -d --name da_mysql --network host \
  -e MYSQL_ROOT_PASSWORD=root_pw -e MYSQL_DATABASE=ecommerce -e TZ=UTC \
  -v "$PWD/sample_data/mysql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" \
  mysql:8.0 --skip-name-resolve --default-time-zone=+00:00
```

只读账号：`readonly` / `readonly_pw`（仅 SELECT 权限）。

### 2. 启动后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # 填入你的 LLM_API_KEY
.venv/bin/uvicorn app.main:app --port 8000
```

`.env` 配置项：

```bash
LLM_BASE_URL=https://api.deepseek.com/v1   # 或任意 OpenAI 兼容服务
LLM_API_KEY=sk-xxx                          # 你的密钥
LLM_MODEL=deepseek-chat
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

### 4. 配置数据源

1. 前端「管理」页 → 新增数据源，填 MySQL/PostgreSQL 连接信息（务必使用**只读账号**）
2. 点「采集元数据」，系统读取表结构
3. 编写语义模型 YAML（度量口径、维度层级、表间关联），见 `docker/sample_data/semantic_model_order.yaml`
4. 在「查询」页用自然语言提问

## 语义模型示例

```yaml
model: order_model
table: fact_orders

columns:
  - business_name: 订单金额
    physical: order_amount
    type: decimal
    unit: 元

measures:
  - business_name: 营收
    expression: SUM(order_amount)
    description: 订单金额之和

dimensions:
  - business_name: 地区
    physical: region
    hierarchy: [地区, 省, 市, 门店]   # 下钻层级

joins:
  - model: customer_model
    key: customer_id
    direction: left
```

## 安全说明

- 数据源请使用**仅 SELECT 权限的只读账号**
- 平台执行前做 SQL 静态校验（sqlglot 只读校验 + 白名单对象）
- 业务数据不进入 LLM（出域白名单：仅表头/列名/注释、语义模型摘要、脱敏报错、相对分档事实）

## License

待定（发布前请补充）
