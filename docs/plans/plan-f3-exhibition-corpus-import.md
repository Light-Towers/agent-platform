# Plan：F3 会展知识语料导入 knowledge-service 验收闭环

> **状态**：Draft v1 / 待评审
> **定位**：将 `D:\0-mingyang\文档` 下的会展行业文档导入 knowledge-service，跑通"采集→标注→审核→发布→可检索"闭环，解除 P0 硬阻塞 F3
> **触发**：用户要求从 `D:\0-mingyang\文档` 开始梳理可用语料并制定导入方案
> **依据**：`docs/plans/plan-exhibition-p0-p1-landing.md` §2.3 件 08 + F03 契约
> **范围**：首期 5 份真实手册导入闭环 + 全量语料分类清单 + 部署方案
> **不在范围**：P1 知识 Agent skill 实现（依赖本方案完成后的 knowledge-service 可检索状态）、nl2sql-service 接入、env var 重命名

---

## 1. 语料梳理结果

### 1.1 分类方法

按**是否适合导入 knowledge-service**（文本型知识语料 vs 结构化数据 vs 技术文档）和**格式**（PDF / DOCX / PPTX / XLSX / MD）分类。

### 1.2 A 类：可直接导入的知识语料（PDF）

> knowledge-service `node_entry.py` 原生支持 PDF，MinerU 云端 API 解析 PDF→MD。

| # | 路径 | 格式 | 知识空间 | 说明 |
|---|------|------|----------|------|
| A1 | `搭建商手册/2024中国进口博览会搭建商手册.pdf` | PDF | exhibition_public | 报馆/搭建流程，直接对应验收场景 |
| A2 | `搭建商手册/【国家会议中心】2021年服贸会展览搭建服务手册2.0版.pdf` | PDF | exhibition_public | 搭建服务手册 |
| A3 | `展会GB标准/GBT+33490-2025展览展示工程服务基本要求.pdf` | PDF | exhibition_public | 国标：展览展示工程服务基本要求 |
| A4 | `展会GB标准/GBT+30521-2025经济贸易展览会数据统计规则.pdf` | PDF | exhibition_public | 国标：数据统计规则 |
| A5 | `展会GB标准/GBT+31082-2025展览会数据审核规范.pdf` | PDF | exhibition_public | 国标：数据审核规范 |
| A6 | `展会GB标准/GBT+35659-2017经济贸易展览会分级与评定准则.pdf` | PDF | exhibition_public | 国标：分级与评定准则 |
| A7 | `展会GB标准/GBT+41129-2021绿色站台评价指南.pdf` | PDF | exhibition_public | 国标：绿色站台评价 |
| A8 | `展会GB标准/GBT+42496-2023绿色展览运营指南.pdf` | PDF | exhibition_public | 国标：绿色展览运营 |
| A9 | `展会GB标准/GBT+45704-2025线上展览会服务指南.pdf` | PDF | exhibition_public | 国标：线上展览会服务 |
| A10 | `杭州大会展中心二期项目建设方案 v1.7 - AI智能问答.pdf` | PDF | exhibition_public | 建设方案 |
| A11 | `大数据/原架构设计文档.pdf` | PDF | exhibition_public | 架构设计 |
| A12 | `语音平台对接.pdf` | PDF | exhibition_public | 语音平台对接方案 |
| A13 | `找客易-搜索服务响应慢优化.pdf` | PDF | exhibition_public | 搜索优化 |
| A14 | `数据治理/数据二十条-中共中央国务院关于构建数据基础制度更好发挥数据要素作用的意见.pdf` | PDF | exhibition_public | 数据二十条政策 |
| A15 | `数据治理/《数据安全治理白皮书 4.0》.pdf` | PDF | exhibition_public | 数据安全治理 |
| A16 | `数据治理/数据体系.pdf` | PDF | exhibition_public | 数据体系 |

### 1.3 B 类：需扩展格式支持后导入的知识语料（DOCX/PPTX）

> MinerU 云端 API 原生支持 DOCX/DOC/PPT/PPTX/XLS/XLSX→MD（≤200MB/200页）。
> 需修改 `node_entry.py` 扩展入口格式判断（当前仅 `.pdf`/`.md`）。

#### B1：DOCX（MinerU 原生支持）

| # | 路径 | 格式 | 说明 |
|---|------|------|------|
| B1-1 | `博博会/0506第十一届博博会参展协议（博物馆）.docx` | DOCX | 参展协议 |
| B1-2 | `博博会/0506第十一届博博会参展协议（企业）.docx` | DOCX | 参展协议 |
| B1-3 | `博博会/2024年乐器展展览服务协议-单页（多个展位）.docx` | DOCX | 服务协议 |
| B1-4 | `博博会/第十一届博博会展位确认函-表格.docx` | DOCX | 展位确认函 |
| B1-5 | `第十届博博会参展协议（博物馆）-已审核0613(1).docx` | DOCX | 参展协议 |
| B1-6 | `第十届博博会参展协议（企业）-已审核0613(1)(1).docx` | DOCX | 参展协议 |
| B1-7 | `6、智慧博物馆信息化系统采购招标技术要求(7).docx` | DOCX | 招标技术要求 |
| B1-8 | `杭州大会展中心二期项目建设方案 - AI智能问答.docx` | DOCX | 建设方案 |
| B1-9 | `畜博会报告/2025中国畜牧业博览会观众数据分析v6.docx` | DOCX | 观众数据分析 |
| B1-10 | `畜博会报告/畜博会20250701增补的数据.docx` | DOCX | 增补数据 |
| B1-11 | `深圳会展中心项目/关于深圳会展中心数字化转型提升...docx` | DOCX | 数字化转型规划 |
| B1-12 | `深圳会展中心项目/数字化转型规划设计12012.docx` | DOCX | 数字化转型规划 |
| B1-13 | `深圳会展中心项目/技术偏离表v1.docx` | DOCX | 技术偏离表 |
| B1-14 | `数据治理/睿治-数据治理知识点总结-分享版.docx` | DOCX | 数据治理知识 |
| B1-15 | `智会智展报告类资讯数据维度梳理@1125_实现分析.docx` | DOCX | 数据维度梳理 |
| B1-16 | `智慧场馆数据治理/综合服务系统需求文档.docx` | DOCX | 需求文档 |
| B1-17 | `智慧场馆数据治理/智慧城市数据中台建设方案.docx` | DOCX | 建设方案 |
| B1-18~20 | `智慧场馆数据治理/（1224-5 项目实施方案...）.docx/.txt` | DOCX/TXT | 投标文件 |
| B1-21~23 | `智慧场馆数据治理/智慧场馆*需求文档.doc` | DOC(旧格式) | 需求文档 |

#### B2：PPTX/PPT（MinerU 原生支持，但内容以图表为主，知识密度低）

| # | 路径 | 格式 | 说明 |
|---|------|------|------|
| B2-1 | `数据治理/杭州大会展中心二期项目建设方案 v1.6.pptx` | PPTX | 建设方案 |
| B2-2 | `数据治理/智慧场馆-数据治理-睿智-v1.0.pptx` | PPTX | 数据治理 |
| B2-3 | `深圳会展中心项目/会展中心数字化提升规划方案-v7.1.pptx` | PPTX | 规划方案 |
| B2-4 | `大数据/果然大数据架构.pptx` | PPTX | 大数据架构 |
| B2-5 | `大数据/数据分析思维.pptx` | PPTX | 数据分析 |
| B2-6 | `大数据/bigdata-architecture.pptx` | PPTX | 架构 |
| B2-7~9 | `智慧场馆数据治理/智慧展览馆大数据...pptx` | PPTX | 解决方案 |
| B2-10 | `智慧场馆数据治理/智慧艺术中心...pptx` | PPTX | 解决方案 |
| B2-11 | `智慧场馆数据治理/智慧展馆智能化系统顶层设计共48页.ppt` | PPT(旧格式) | 顶层设计 |

### 1.4 C 类：结构化数据（非知识语料，适合 nl2sql-service）

> XLSX/CSV 是结构化数据，不适合向量检索，应走 nl2sql-service 的 SQL 问数链路。

| 分类 | 文件数 | 说明 |
|------|--------|------|
| `畜博会产业链/` | 11 | 参展商数据、产业链标签（csv/xlsx/txt） |
| `会刊/` | 2 | 展商名单、名片（xlsx） |
| `场馆统计报表/` | 14 子目录 | 财务/场地/合同等报表（xls/xlsx） |
| `大数据/表整理/` | 6 | 数据库表结构（xls/xlsx） |
| `大数据/畜博会/` | 6 | 观众数据分析（xlsx/sql） |
| `大数据/数据同步/` | 3 | 工商企业数据（xlsx/sql） |
| `找客易/找客易-字段原始数据枚举整理.xlsx` | 1 | 字段枚举 |
| `找客易/找客易&爱企查&天眼查数据对比.xlsx` | 1 | 数据对比 |
| `特征词-industry_chain.xlsx` | 1 | 特征词 |
| `深圳会展中心项目/人员工作安排.xlsx` | 1 | 工作安排 |
| `深圳会展中心项目/智慧场馆系统平台报价清单.xlsx` | 1 | 报价清单 |
| `深圳会展中心项目/深圳会展中心数字化提升项目一阶段时间进度表(1).xls` | 1 | 进度表 |

### 1.5 D 类：技术/接口文档（非知识语料，系统设计参考）

> MD/接口设计文档是系统开发参考，非业务知识，不导入 knowledge-service。

| 分类 | 文件数 | 说明 |
|------|--------|------|
| `接口设计/` | 2 | 果然网接口、主场-搭建商接口（md） |
| `找客易/` | 10 | 搜索服务接口、字段梳理等（md/png） |
| `大数据/` | 3 | 架构图、SQL（drawio/sql/pdm） |
| `飞致云/` | 4 | DataEase/MaxKB/SQLBot 产品介绍（pdf） |
| `Aistudio/` | 2 | AIstudio 使用方法（docx） |
| `环境地址.md` | 1 | 环境配置 |
| `生产服务参数配置.md` | 1 | 服务配置 |
| `日报、周报.md` | 1 | 工作记录 |
| `Doris-报表sql.md` | 1 | SQL |
| `Untitled*.md` | 2 | 未命名 |
| `Saas服务.vsdx` | 1 | Visio 图 |

### 1.6 统计

| 类 | 文件数 | 导入 knowledge-service | 说明 |
|----|--------|----------------------|------|
| A（PDF） | 16 | ✅ 直接导入 | 原生支持 |
| B1（DOCX/DOC） | ~23 | ✅ 扩展格式后导入 | MinerU 原生支持，改 node_entry.py |
| B2（PPTX/PPT） | ~11 | ⚠ 可选导入 | MinerU 支持，但知识密度低 |
| C（结构化数据） | ~47 | ❌ 走 nl2sql-service | 非知识语料 |
| D（技术文档） | ~27 | ❌ 不导入 | 系统设计参考 |
| **合计** | **~124** | **A+B1+B2 ≈ 50** | |

---

## 2. 首期 5 份语料选择

### 2.1 选择依据

- F03 §2 首期建议 3-5 份真实手册
- P1 知识 Agent 验收场景："参展商问报馆需要哪些材料？"
- 覆盖报馆流程 + 国标 + 参展协议三类核心知识
- 4 份 PDF（无需改代码）+ 1 份 DOCX（验证 MinerU DOCX 转换链路）

### 2.2 首期清单

| # | 路径 | 格式 | Metadata | 验收场景 |
|---|------|------|----------|----------|
| 1 | `搭建商手册/2024中国进口博览会搭建商手册.pdf` | PDF | scope_type=PUBLIC, authority=进口博览会组委会 | "报馆需要哪些材料？" |
| 2 | `搭建商手册/【国家会议中心】2021年服贸会展览搭建服务手册2.0版.pdf` | PDF | scope_type=PUBLIC, authority=国家会议中心 | "搭建服务流程？" |
| 3 | `展会GB标准/GBT+33490-2025展览展示工程服务基本要求.pdf` | PDF | scope_type=PUBLIC, authority=国家标准化管理委员会 | "展览展示工程服务要求？" |
| 4 | `展会GB标准/GBT+30521-2025经济贸易展览会数据统计规则.pdf` | PDF | scope_type=PUBLIC, authority=国家标准化管理委员会 | "数据统计规则？" |
| 5 | `博博会/0506第十一届博博会参展协议（博物馆）.docx` | DOCX | scope_type=PUBLIC, authority=博博会组委会 | "参展协议条款？" |

### 2.3 Metadata 标注

每份语料导入时传入以下 metadata（`/upload` Form 字段）：

```python
{
    "scope_type": "PUBLIC",           # 公开知识空间
    "tenant_id": "exhibition",        # 会展租户
    "tenant_type": "enterprise",      # 企业级
    "effective_from": "2025-01-01",   # 生效起始日
    "effective_to": "",               # 无截止（长期有效）
    "version": "v1",                  # 知识版本
    "authority": "<发布方>",          # 发布授权方
    "status": "PUBLISHED",            # 直接发布（首期跳过审核流程）
    "enable_item_name_recognition": False,  # 关闭电商商品名 NER（非电商语料）
}
```

---

## 3. 部署架构

### 3.1 拓扑

```text
┌─ 本地 Windows (D:\0-mingyang\文档) ──────────────────────────┐
│  语料源（PDF/DOCX）                                          │
│  上传脚本（curl / python requests → 126:8000/upload）         │
└────────────────────────────────────────────────────────────────┘
                          │ HTTP
                          ▼
┌─ 远程 192.168.100.126 (Docker) ──────────────────────────────┐
│  knowledge-service 全栈（docker-compose --profile core up）   │
│    web (:8000)      ← FastAPI 导入/查询入口                  │
│    milvus (:19530)  ← 向量库（BGE-M3 稠密+稀疏）              │
│    etcd (:2379)     ← Milvus 元数据                          │
│    minio (:9000)    ← 对象存储（PDF 原件 + 图片）             │
│    mongo (:27017)   ← 会话历史                               │
│    neo4j (:7687)    ← 知识图谱                                │
└────────────────────────────────────────────────────────────────┘
                          │ API
                          ▼
┌─ 云端服务 ───────────────────────────────────────────────────┐
│  MinerU API (https://mineru.net/api/v4)  ← PDF/DOCX→MD 解析  │
│  硅基流动 API (https://api.siliconflow.cn/v1) ← embedding/rerank │
│  LLM API (OPENAI_BASE_URL) ← 答案生成                        │
└────────────────────────────────────────────────────────────────┘
```

### 3.2 配置

**126 服务器 `.env`**（knowledge-service）：

```env
# 应用
APP_HOST=0.0.0.0
APP_PORT=8000

# MinerU 云端（PDF/DOCX→MD 解析）
MINERU_BASE_URL=https://mineru.net/api/v4
MINERU_API_TOKEN=<用户提供>

# Embedding + Reranker：API 模式（无需本地 torch/模型）
EMBEDDING_MODE=api
RERANK_MODE=api
SILICONFLOW_API_KEY=<用户提供>
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_EMBEDDING_MODEL=BAAI/bge-m3
SILICONFLOW_RERANK_MODEL=BAAI/bge-reranker-v2-m3

# LLM（答案生成 + item_name NER，后者已关闭）
OPENAI_BASE_URL=<用户提供>
OPENAI_API_KEY=<用户提供>
LLM_DEFAULT_MODEL=<用户提供>

# Milvus / Neo4j / MinIO / Mongo（docker-compose 内服务名互访）
MILVUS_URL=http://milvus:19530
NEO4J_URI=bolt://neo4j:7687
NEO4J_PASSWORD=<设置>
MONGO_URL=mongodb://mongo:27017
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=<设置>
MINIO_SECRET_KEY=<设置>

# 关闭电商商品名 NER（会展语料不需要）
ITEM_NAME_DIAG=0

# 鉴权（首期关闭，便于测试；生产开启）
ZHANGUI_API_KEY=
```

### 3.3 外部资源依赖清单

| # | 资源 | 用途 | 来源 | 状态 |
|---|------|------|------|------|
| 1 | 192.168.100.126 SSH | 部署 Docker 全栈 | 用户管理 | ✅ 已知 |
| 2 | MinerU API Token | PDF/DOCX→MD 解析 | https://mineru.net API 管理页面创建 | 🔴 需用户提供 |
| 3 | 硅基流动 API Key | Embedding + Reranker | https://siliconflow.cn 注册 | 🔴 需用户提供 |
| 4 | LLM API (base_url + key + model) | 答案生成 | 用户提供（千问/即墨等 OpenAI 兼容） | 🔴 需用户提供 |
| 5 | Neo4j 密码 | 知识图谱 | 自定义设置 | ⚠ 部署时设置 |
| 6 | MinIO 凭据 | 对象存储 | 自定义设置 | ⚠ 部署时设置 |

---

## 4. 代码改动

### 4.1 改动 1：`node_entry.py` 扩展 DOCX/PPTX 格式支持

**文件**：`applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_entry.py`

**现状**（第 36-45 行）：
```python
if document_path.endswith(".pdf"):
    state["is_pdf_read_enabled"] = True
    state["pdf_path"] = document_path
elif document_path.endswith(".md"):
    state["is_md_read_enabled"] = True
    state["md_path"] = document_path
else:
    logger.warning(f"不支持的格式，仅支持.pdf/.md")
```

**目标**：扩展支持 `.docx`/`.doc`/`.pptx`/`.ppt`/`.xlsx`/`.xls`，统一走 MinerU 解析链路（与 PDF 同路径）。

**改动**：
```python
MINERU_SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls")

if document_path.endswith(".pdf"):
    state["is_pdf_read_enabled"] = True
    state["pdf_path"] = document_path
elif document_path.endswith(".md"):
    state["is_md_read_enabled"] = True
    state["md_path"] = document_path
elif document_path.endswith(MINERU_SUPPORTED_EXTENSIONS):
    # DOCX/PPTX/XLSX 走 MinerU 解析（与 PDF 同链路，MinerU 原生支持）
    state["is_pdf_read_enabled"] = True
    state["pdf_path"] = document_path
else:
    logger.warning(f"不支持的格式，仅支持.pdf/.md/.docx/.pptx/.xlsx")
```

**影响面**：仅 `node_entry.py` 入口判断，后续 `node_pdf_to_md.py` 已通过 MinerU API 上传文件（MinerU 根据文件名后缀自动选择解析策略）。

### 4.2 改动 2：`node_pdf_to_md.py` 去除 PDF Content-Type 硬编码

**文件**：`applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_pdf_to_md.py`

**现状**（第 112-114 行）：上传失败时强制 `Content-Type: application/pdf` 重试。

**改动**：根据文件后缀动态设置 Content-Type，或直接不设置（MinerU 根据文件名后缀自动识别）。

**影响面**：仅重试逻辑，不影响首次上传成功率。

### 4.3 改动 3：导入脚本

**新增文件**：`applications/knowledge-service/scripts/import_exhibition_corpus.py`

功能：
- 遍历 `D:\0-mingyang\文档` 下指定语料
- 对每份语料调用 `POST http://126:8000/upload`（multipart/form-data）
- 传入 metadata（scope_type/tenant_id/authority/status/...）
- 轮询 `/status/{task_id}` 直到 completed/failed
- 输出导入报告（成功/失败/耗时）

### 4.4 测试

- `node_entry.py` 新增单元测试：覆盖 `.docx`/`.pptx`/`.xlsx` 格式判断
- `node_pdf_to_md.py` Content-Type 改动不破坏现有 PDF 测试
- 导入脚本 dry-run 模式（不实际上传，只打印计划）

---

## 5. 执行步骤

### 5.1 准备阶段（需外部资源）

| 步骤 | 内容 | 依赖 |
|------|------|------|
| P1 | 用户提供 MinerU API Token | MinerU 注册 |
| P2 | 用户提供硅基流动 API Key | 硅基流动注册 |
| P3 | 用户提供 LLM API 配置（base_url + key + model） | 已有 LLM 服务 |
| P4 | 确认 126 SSH 可访问 | 已知 |

### 5.2 代码改动阶段

| 步骤 | 内容 | 验证 |
|------|------|------|
| C1 | 修改 `node_entry.py` 扩展格式支持 | 单元测试通过 |
| C2 | 修改 `node_pdf_to_md.py` Content-Type | 现有 PDF 测试不破坏 |
| C3 | 新增导入脚本 | dry-run 输出正确 |
| C4 | 跑 `uv run pytest applications/knowledge-service/tests -q` | 全绿 |

### 5.3 部署阶段

| 步骤 | 内容 | 验证 |
|------|------|------|
| D1 | SSH 到 126，拉取最新代码 | git log 确认 |
| D2 | 配置 `.env`（填入 MinerU Token / 硅基流动 Key / LLM 配置） | — |
| D3 | `docker compose --profile core up -d --build` | 全部服务 healthy |
| D4 | `curl http://126:8000/health/ready` | 200 OK |

### 5.4 导入阶段

| 步骤 | 内容 | 验证 |
|------|------|------|
| I1 | 运行导入脚本，上传首期 5 份语料 | 5 个 task_id 返回 |
| I2 | 轮询 `/status/{task_id}` 直到全部 completed | 5/5 completed |
| I3 | 检查 Milvus 集合中有数据 | chunk 数 > 0 |
| I4 | 检查 MinIO 中有 PDF/DOCX 原件 | 5 个对象 |

### 5.5 检索验收阶段

| 步骤 | 内容 | 验收标准 |
|------|------|----------|
| V1 | `POST /query` 问"报馆需要哪些材料？" | 返回答案 + citation |
| V2 | `POST /query` 问"展览展示工程服务基本要求？" | 返回答案 + citation |
| V3 | `POST /query` 问"博博会参展协议条款？" | 返回答案 + citation |
| V4 | 答案中 citation 的 authority/effective_from/version 齐备 | Metadata 完整 |
| V5 | 越权测试：tenant_id=other 查询 scope_type=PRIVATE | 返回空结果 |

### 5.6 全量导入阶段（首期闭环后）

| 批次 | 范围 | 文件数 |
|------|------|--------|
| 批次 2 | A 类剩余 12 份 PDF | 12 |
| 批次 3 | B1 类 DOCX（23 份） | 23 |
| 批次 4 | B2 类 PPTX（可选，11 份） | 11 |

---

## 6. 验收标准

### 6.1 首期闭环验收（F3 解除阻塞）

- [ ] 5 份语料全部导入成功（status=completed）
- [ ] Milvus 中有对应 chunk 数据（向量+稀疏）
- [ ] MinIO 中有原件存储
- [ ] `/query` 检索返回答案 + citation
- [ ] citation 含 authority/effective_from/version/scope_type
- [ ] `enable_item_name_recognition=False` 时跳过 NER 节点
- [ ] DOCX 语料（第 5 份）通过 MinerU 成功转 MD 并入库

### 6.2 代码改动验收

- [ ] `node_entry.py` 支持 .pdf/.md/.docx/.doc/.pptx/.ppt/.xlsx/.xls
- [ ] 现有 knowledge-service 测试全绿（210 passed, 13 skipped 不变）
- [ ] lint 全绿

---

## 7. 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| MinerU API 限频/额度不足 | DOCX 转换失败 | MinerU 每日 1000 页免费额度，首期 5 份远低于限额 |
| 硅基流动 API Key 额度不足 | embedding 失败 | 首期 5 份语料 chunk 数有限，额度充足 |
| 126 服务器资源不足（Milvus 4G+Neo4j+...） | Docker 启动失败 | 126 已跑其他容器，需确认剩余资源；必要时加 swap |
| DOCX 含表格/图片，MinerU 解析质量差 | 检索效果不佳 | MinerU vlm 模型对复杂版式支持好；首期 1 份 DOCX 验证质量 |
| LLM API 不可用 | 答案生成失败 | 导入不依赖 LLM（仅 embedding+rerank）；查询答案生成需 LLM |
| `node_entry.py` 改动引入回归 | 现有 PDF 导入破坏 | 改动仅新增格式分支，不影响现有 .pdf/.md 路径；单元测试覆盖 |

---

## 附：与现有 plan 的关系

| 现有 plan | 关系 |
|-----------|------|
| `plan-exhibition-p0-p1-landing.md` | 本方案是其 §2.3 件 08 的 F3 解除阻塞执行项 |
| `plan-tech-debt-env-var-rename.md` | 本方案中 `.env` 仍用 `ZHANGUI_*` 前缀（变量名重命名是独立技术债务） |
