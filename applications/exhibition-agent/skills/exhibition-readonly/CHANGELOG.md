# exhibition-readonly Skill 变更记录（CHANGELOG）

> **为什么单独建这个文件**：SKILL.md 的 YAML frontmatter 仅支持 `name` / `description`
> （+可选 `allowed-tools` / `disable`），**没有 `version` 字段**。因此版本号与改动历史
> 不写进元数据，而用本文件单独维护。
>
> **维护约定**：每次改动 `SKILL.md`、 `tests/` 或打包资源时，在最上方追加一条。

## 格式
```
## [版本号] - YYYY-MM-DD
- 改了什么（SKILL.md 哪一段 / tests 哪个用例 / 资源文件）
- 影响范围 / 原因
```

---

## [v1.3] - 2026-09-17
- **修复 leads 写操作响应标签 bug（代码层，非仅文档）**：`leads.py` 的 `delete_lead` 两处返回 `status`（正常分支 line ~183 + idempotent 分支 line ~157）由误标的 `pending_approval` 改回 `pending_delete`，与 DB 实际存储态及 OpenAPI 语义一致；同步修正 `leads.py`/`main.py` 注释。已 SFTP 到 `192.168.100.241:/data/exhibition/ontology/backend/` 并 `docker restart exhibition-dashboard` 部署；实测 `DELETE` 现返回 `status:"pending_delete"`（normal + idempotent 两分支均修复），验证后 reject 恢复 active、零残留。

## [v1.2] - 2026-09-17
- **纠正 v1.1 的术语"修正"（那条是错的）**：经核对 `ontology/web/backend/datamod/leads.py`，W3 `DELETE` 真实存储态是 `pending_delete`（软删除待确认），响应 `status` 误标成 `pending_approval`（代码 `leads.py:177-184` 的标签 bug）。`confirm` 按 **DB 实际状态** 分支：`pending_delete`→`deleted`、`pending_approval`(仅 W1 在 `all` 策略创建时才有)→`active`。故把 SKILL.md 写操作段的状态名从 `pending_approval` 改回 `pending_delete`，并标注该响应标签 bug。
- 补充 `/confirm` body 必填（无 JSON 会 422，可传 `{}`）、`main.py` 无 `GET /leads/{id}` 故删除须直接查 SQLite `t_agent_lead` 核验 `status='deleted'`+`deleted_at` 的落库说明。

## [v1.1] - 2026-09-17
- 迁移到项目级 `skills/exhibition-readonly/`（原 `.codebuddy/skills/exhibition-readonly/`），作为业务资产随 git 共享。
- 去掉 skill 内写死的 IP `192.168.100.241:8000`：后端基址统一走环境变量 `EXHIBITION_API_BASE_URL`（frontmatter description、后端地址段、示例行三处同步修正）。
- 术语修正：`pending_delete` → `pending_approval`（实际软删状态字段名，此前文档写错）。
- 新增 `tests/` 回归测试集：`golden_cases.json`（层1 api_contract 22 条 + 层2 prompt_routing 6 条）+ `run_golden_api.py`（层1 直连 HTTP 不需 LLM key；层2 需 key 才能跑）。

## [v1.0] - 初始版本（早于 2026-09-17，具体日期待补）
- 建立会展只读查询 skill：实体检索/画像（展会/展商/观众/场馆/主办）、概览、业务记录（合同/安全/会议/线索）、场馆五张卡片（辐射/定位/档期/白皮书/推荐）、招商与展会推荐、外部亲和、策略洞察、预测与热度等只读端点的能力总表。
- 写操作（create/delete lead）仅作说明不调用，遵守 HITL 软删除与 INV-5 红线；结果须尊重 `data_readiness` 标注，不编造数据。
