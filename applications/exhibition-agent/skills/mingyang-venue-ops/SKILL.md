---
name: mingyang-venue-ops
description: 当用户需要查询或受限地操作明阳平台内网系统（192.168.100.9）的数据时调用，覆盖三大模块：① mingyang-sys 主场运营工作台——项目列表（home/orgProject/page）、角色/部门/账号管理、分类树、单位主题配置（多数为 POST 查询，少数 GET）；② mingyang-builder 建造/企业模块——施工企业/全部企业列表等（实测 200）；③ mingyang-company `/site` 门户——展商报名信息（exhibitor/page）、企业信息、证件、客户、论文集等（`/mingyang-company/api/company/site/*`，用**另一套站点令牌**）。亦含写操作（如 /private/user/save 保存用户信息）。只读调用随时可用；写操作（POST/PUT/DELETE）默认禁止自主调用，须用户显式确认（HITL 红线）后才执行，因 JWT 即用户本人真实登录态。基址由 MINGYANG_API_BASE_URL 配置，JWT 由 MINGYANG_JWT（及站点令牌）配置。
---

# 明阳平台查询/操作 Skill（mingyang-sys 主场运营 + mingyang-builder 建造企业 + mingyang-company /site 门户）

一组封装明阳平台内网系统（mingyang-sys 主场运营工作台、mingyang-builder 建造/企业模块）HTTP 端点的 skill，供你在对话中调用：只读 GET 随时可用；写操作（POST）须用户显式确认（HITL）。JWT 即用户本人真实登录态，写操作落到真实生产账号。

## 后端地址（需配置，勿写死 IP）

> 基址通过环境变量 **`MINGYANG_API_BASE_URL`** 提供（例如 `http://192.168.100.9`）。**本 skill 内禁止写死 IP/域名**，统一用该变量拼接。
> 鉴权令牌通过环境变量 **`MINGYANG_JWT`** 提供（用户从浏览器 DevTools 复制的会话 JWT；含真实登录态，谨慎使用，勿外泄、勿提交）。

- Base URL：`{MINGYANG_API_BASE_URL}`
- API 路径前缀：`/mingyang-sys/api/sys/...`
- 端点清单来源：mingyang-builder 来自后端 Controller 目录（`builder_endpoints.json` 全量 502 端点）+ 带权实测；mingyang-sys 来自**前端 API 模块**（`app.js` 中 `VUE_APP_SYS + "<path>"` 动态拼接，共 56 个真实路径）+ 带权实测；mingyang-company 来自 **`/site/static1/js/app.js`**（`VUE_APP_COMPANY + "<path>"`，共 53 个 `site/*`）+ 带权实测。
- ⚠️ **勘误（2026-09-18）**：早期 manifest/SKILL 里的 `workbench/home/itemList`、`workbench/task/list`、`workbench/message/list`、`workbench/unit/list`、`home/statistics`、`user/info` 是把**前端路由**误当前缀 API 拼出的**幽灵端点**（后端目录与前端 JS 中均不存在），其 401 只代表"路径不存在"，**不代表权限不足**。已全部删除并替换为真实端点。

## 鉴权与请求约定（重要）

- 该系统 API 校验**依赖同源 `Referer`**：请求必须带 `Referer` 指向同域页面（如 `http://192.168.100.9/workbench/home/...`），否则返回 **401「未登录」**（实测：缺 `Referer` 时全部 API 401；用户抓包中 `buildCompany/page` 带 `Referer`+cookie 即 200，`getThemeConfig` 此前亦 200）。`Origin` 头非必需（该抓包未带 Origin、仅靠 `Referer`+cookie 即 200），但为稳妥可一并带上。注意：**静态 JS 资源本身公开、无需鉴权即可拉取**，故端点反查不依赖有效 token。
- 同时携带：
  - 请求头 `jwt-token: {MINGYANG_JWT}`
  - Cookie `SET_TOKEN_HOME={MINGYANG_JWT}`（两个都带最稳）
- 全部为 **GET** 请求。示例：
  ```bash
  curl '{MINGYANG_API_BASE_URL}/mingyang-sys/api/sys/workbench/unit/getThemeConfig' \
    -H 'jwt-token: {MINGYANG_JWT}' \
    -H 'Referer: {MINGYANG_API_BASE_URL}/workbench/home/accountSettings' \
    --cookie 'SET_TOKEN_HOME={MINGYANG_JWT}'
  ```

## 端点速查（状态以带权实测为准）

### 模块一：mingyang-sys（主场运营工作台）

> **路径来源**：前端 API 模块 `src/api/mingyang-sys.js`（打包在 `app.js` 内，`VUE_APP_SYS + "<path>"` 动态拼接，前缀 `/mingyang-sys/api/sys/`），共 56 个端点。
> **方法**：多数业务查询是 **POST + query params**（axios `params`，非 body），少数为 GET。**切勿用 GET 调 POST 端点**——会 HTTP 200 但 body `code=500「服务器繁忙」`。

**项目列表（核心）：`POST /mingyang-sys/api/sys/home/orgProject/page`**（params `page`、`pageSize`）→ 实测 `code=200`，`data.pageInfo.list[]`，字段 `{id,itemName,unitName,tradeTypeVal,createTime,boothCount,...}`。

| 端点（前缀 `/mingyang-sys/api/sys/`） | 方法 | 用途 | 实测 |
| --- | --- | --- | --- |
| `home/orgProject/page` | POST | **项目列表**（按条件分页查询） | ✅ 200 |
| `home/orgProject/check` | GET | 项目校验 | ✅ 200 |
| `sysOrgClient/getAccountClientAuthority` | GET | 当前账号机构权限 | ✅ 200 |
| `workbench/unit/getThemeConfig` | GET | 单位主题配置 | ✅ 200 |
| `workbench/role/page` / `workbench/role/queryList` | POST | 角色管理 | ✅ 200 |
| `workbench/department/queryList` / `department/page` | POST | 部门管理 | ✅ 200 |
| `workbench/account/page` | POST | 账号管理 | ✅ 200 |
| `workbench/classify/queryTree` | POST | 分类树 | ✅ 200 |
| `workbench/receivingAccountConfig/list` | GET | 收款账户配置 | ✅ 200 |
| `org/*`、`permission/*`、`login/log/page` | POST | 机构/权限/登录日志（**机构级**） | ⛔ 401 |

> **带权实测（2026-09-18）**：本 `workbench` 账号对 **56 个真实 sys 端点中 38 个返回 200**（项目/角色/部门/账号/分类/主题等业务功能全部可用）。真正 401 的只有**机构级/系统管理员级**端点（`org/page`、`org/get`、`permission/*`、`login/log/page`），属正常权限边界。
> ⚠️ **勘误**：早期版本列的 `workbench/home/itemList`、`workbench/task/list`、`workbench/message/list`、`workbench/unit/list`、`home/statistics`、`user/info` 是**幽灵端点**（前端路由误拼），已删除。**项目列表的真实接口是 `home/orgProject/page`。**
> ✅ **已纳入回归**：`home/orgProject/page`、`workbench/role/page`、`department/queryList`、`account/page`、`classify/queryTree`（POST 只读查询）、`unit/getThemeConfig`、`sysOrgClient/getAccountClientAuthority`（GET）、`home/orgProject/check`（GET）已进 L1 断言 + L2 黄金主；`org/page`、`permission/page` 作为 401 权限边界纳入。

### 模块二：mingyang-builder（场馆运营 / 主场树，已带权实测 ✅）

- 本 JWT（`permissionTag=workbench`，**场馆运营角色**）对 builder 的 **`/home/*` 主场树**全部 GET 端点**授权可达**（HTTP 非 401）。
- 共确认 **116 个 GET 端点（含 2 个 `{id}` 路径参数模板），覆盖 43 个业务域**。完整清单 + 每个端点的返回字段 schema：
  - 无上下文版：`.codebuddy/scripts/builder_schema_catalog.txt`
  - 带 `exhibitionId` 版：`.codebuddy/scripts/builder_schema_catalog_ctx.txt`（解锁后 **33 个端点出真实数据**）
  - 全量 502 端点（含 `/build/*` 搭建商自助树与 `/feign/*` 内部树）：`builder_endpoints.json`
- 就绪度（**均非权限问题**）：
  - ✅ **零参数即出数据**：见「即用端点」（会话默认展会上下文已够）。
  - ✅ **带 `exhibitionId` 出数据**：先 `GET .../home/h5/exhibition/getExhibitionListByProject`（共 43 个展会）取 `id`，再给 list/map/statistic 类端点追加 `?exhibitionId=<id>` → 33 个端点出真实数据（展位地图、坐标、撤展、施工图、费用/收款统计等）。
  - ⚠️ **实测注意**：① 该列表返回顺序**不稳定**，取"首项"两次可能不同展会，选定 `exhibitionId` 后务必固定使用；② 端点**响应结构恒合法**（HTTP 200 + 正确 schema），但行数取决于该展会自身是否已有数据——如 `2025第二十届大河国际珠宝展` 的 `boothStatistics` 全为 0、`carCert/page` 为 0 行（该展会暂无展位/车证数据），而 `boothRemoval/page` 有 1 行。"出数据"指能力可达，非空数据保证。
  - ⚠️ **按记录 `id` 查**（业务 code=301/303）：`detail/info/getById` 类端点需先用对应 `page/list` 拿到记录 `id` 再查（正常 REST 链式，非权限问题）。
  - ❌ 真正 401 的是 `/build/*`（搭建商自助）树与 `/feign/*`（内部调用）——本账号无搭建商权限（与分支 `feature/venue-operator-capability` 一致）。

#### 即用端点（零参数，实测 200 + 真实数据）

| 端点 | 返回结构（首行字段） | 用途 |
| --- | --- | --- |
| `GET /mingyang-builder/api/builder/home/contractor/page` | [{id,exhibitName,companyName,hallName,areaName,boothNo,auditStatus,...}] | 承建商报馆分页 |
| `GET /mingyang-builder/api/builder/home/h5/exhibition/getExhibitionListByProject` | [{id,name,startTime,endTime,entranceStatus,status}] | 项目下展会列表（**取 exhibitionId 用**） |
| `GET /mingyang-builder/api/builder//home/private/workbench/buildCompany/page` ⚠`//` | [{id,name,contacts,contactsPhone,socialCreditCode,createTime}] | 施工企业/企业列表 |
| `GET /mingyang-builder/api/builder/build/workbench/booth/none/getBoothList` | [{boothId,boothNo,boothArea,boothType,hall,area,companyName,buildCompanyName,...}]（964KB） | 全量展位 |
| `GET /mingyang-builder/api/builder/home/page/backlog` | {contractorAuditCount,leasedGoodsAuditCount,refundAuditCount,...} | 工作台待办统计 |
| `GET /mingyang-builder/api/builder/home/page/booth` | {allBoothCount,allBoothUseCount} | 展位概览 |
| `GET /mingyang-builder/api/builder/home/page/getBoothCompleted` | {allBoothCount,completedBoothCount,unFinishedBoothCount} | 展位完成度 |
| `GET /mingyang-builder/api/builder/home/statistic/boothStatistic` | {totalArea,useTotalArea,unusedTotalArea,...} | 展位面积统计 |
| `GET /mingyang-builder/api/builder/home/statistic/builderStatistic` | {builderCount,builderAssignCount,contractorCount,...} | 搭建商统计 |
| `GET /mingyang-builder/api/builder/home/h5/work-drawing/getBoothCompleted` | {allBoothCount,completedBoothCount,unFinishedBoothCount} | 施工图完成度 |
| `GET /mingyang-builder/api/builder/build/pay/none/payConfig` | {payTypes,onlinePayEnabled,totalAmount} | 支付配置 |

> 路径含 `//` 双斜杠（`builder//home`）的端点须保持原样。查询参数：`page`、`pageSize`、`field`、`sortBy`。

> **⚠️ 零参数端点分两类（2026-09-18 回归测试实测）**：
> - **真正全局（不依赖展会，硬断言有数据）**：`contractor/page`、`getExhibitionListByProject`、`buildCompany/page(//)`、`getBoothList(none)`、`pay/none/payConfig` —— 任意时刻调用均出真实数据。
> - **默认展会作用域（用服务端"当前默认展会"；不传 `exhibitionId` 时数据有无随默认展会漂移）**：`page/backlog`、`page/booth`、`page/getBoothCompleted`、`statistic/boothStatistic`、`statistic/builderStatistic`、`h5/work-drawing/getBoothCompleted`。它们**不是真正的零参数即用**——后端按 session 默认展会返回，默认展会若恰为无数据的展会（如 `2025第二十届大河国际珠宝展`）则返回空。要稳定出数据，显式追加 `?exhibitionId=<有数据的展会>`。回归测试中这 6 个仅断言"结构合法"，不要求非空。

#### 带 `exhibitionId` 激活的典型 GET 端点（取 id 后追加 `?exhibitionId=<id>`）

- `GET .../home/booth/map/getBoothMapInfoAndBoxLocation` → 展位地图+底图+坐标
- `GET .../home/booth/map/boothStatistics` → {totalBoothCount,reportedBoothCount,completedCount,...}
- `GET .../home/booth/map/getBoothCoordinateList` → 展位坐标列表
- `GET .../home/h5/booth/map/getBoothMapInfoAndBoxLocation` → H5 展位地图
- `GET .../home/boothRemoval/page` / `.../home/h5/boothRemoval/page` → 撤展列表
- `GET .../home/work-drawing/getBoothList` / `.../home/work-drawing/getBoothConstructionCompletedList` → 施工图列表/完工列表
- `GET .../home/statistic/contractorStatisticDataExport` 等统计导出（⚠ GET 触发导出任务，名含 stat 但为导出）
- 完整 33 个见 `builder_schema_catalog_ctx.txt`。

### 模块三：mingyang-company（`/site` 门户，展商/观众报名站）

> `/site` 是**独立前端 + 独立鉴权**（cookie `SET_TOKEN`，非 workbench 的 `SET_TOKEN_HOME`），登录走 `mingyang-auth`（`POST /mingyang-auth/api/auth/site/login`）。它聚合多个微服务：`mingyang-company`（`VUE_APP_COMPANY=/mingyang-company/api/company/`，53 个 `site/*` 端点）、`mingyang-operation`（观众）、`mingyang-public`、`mingyang-auth` 等。页面如 `/167/site/user/registrationInformation`（个人中心-报名信息）。
> **注意**：workbench JWT 对 company 认证端点**无效**（`401/code=204「无权限访问」`，文案异于 sys）；须用**站点令牌**（`.codebuddy/scripts/.mingyang_site_jwt`，浏览器 cookie `SET_TOKEN`）。

**展商报名信息（本模块核心，对应页 `/167/site/user/registrationInformation`）：`GET /mingyang-company/api/company/site/exhibitor/page`**（params `page`/`pageSize`；⚠ 该端点 **GET 出数据、POST 恒 500**，与前端 `method:post` 声明不符，以实测为准）。

| 端点（前缀 `/mingyang-company/api/company/`） | 方法 | 用途 | 实测 |
| --- | --- | --- | --- |
| `site/exhibitor/page` | GET | **展商报名信息列表** | ✅ 200 带数据 |
| `site/exhibitor/task-steps` | GET | 报名流程步骤 | ✅ 200 |
| `site/company/datail` | GET | 当前企业信息 | ✅ 200 |
| `site/certificate/history/statistics` | GET | 证件历史统计 | ✅ 200 |
| `site/certificate/page` | POST | 证件分页 | ✅ 200 |
| `site/customer/page` | POST | 客户分页 | ✅ 200 |
| `site/proceedings/query` | POST | 论文集查询 | ✅ 200 |
| `site/userApplyMessage/getMyStatistics` | POST | 个人中心统计 | ✅ 200 |

> 以上 8 个即 **F.company 回归组**。另有 `site/product/*`、`site/booking/*`、`site/ProductIntention/*`、`site/group/*`（部分免登录可 200、部分需参数），以及 `site/*/save|delete|edit|import|export|addCompany|updateCompany` 等**写端点**（同样 HITL，未穷举）。

**`/site` 门户其他微服务（G.portal 回归组）**：同一站点令牌可用。报名页对**观众分支(type==8)**改调 `mingyang-operation` 的 `audience/page` + `mingyang-public`。

| 端点 | 方法 | 用途 | 实测 |
| --- | --- | --- | --- |
| `/mingyang-operation/api/operation/site/audience/page` | POST | **观众报名分页**（报名页 type==8） | ✅ 200 |
| `/mingyang-operation/api/operation/site/information/page` | POST | 资讯分页 | ✅ 200 |
| `/mingyang-operation/api/operation/site/invitation/queryEffectiveInvitation` | GET | 有效邀请函 | ✅ 200 |
| `/mingyang-public/api/public/site/classify/queryParentClassify` | POST | 分类 | ✅ 200 |

> 上述均用站点令牌（`jwt:"site"`）。其余服务基址参考：`mingyang-order`（`/mingyang-order/api/order/`，订单/合同/发票/退款）、`mingyang-exhibition`（`/mingyang-exhibition/api/exhibition/`）、`mingyang-common`、`mingyang-base`、`mingyang-auth`。

## 写操作边界（POST/PUT/DELETE，共 192 个 · HITL 红线）

写端点**默认不调用**,纳入 skill 仅表示"经你确认后可执行",**绝不由 Agent 自主发起**。JWT 即用户本人真实登录态,任何写操作都会落到真实生产账号。以下按业务域列出(完整 192 个见 `builder_endpoints.json` 中 `http∈{POST,PUT,DELETE}`)。

### 高危写操作（务必二次确认，多为不可逆/状态变更）
- **审核类**:报馆 `contractor/audit`、搭建申请 `buildApply/auditStatus`、车证 `carCert/audit`、撤展 `boothRemoval/audit`/`auditBatch`、退款 `refundOrder/refundOrderExamine` 与 `homeH5OrderExamine`、发票 `financial/invoice/review`、商品收款 `goodsCollection/offlinePaymentOrderExamine`、搭建商认证 `buildCompany/auditBuildCompanyAuthById`
- **删除/作废类**:展会 `exhibition/delete`、撤展 `boothRemoval/delete`、商品类型 `goodsConfig/delete`、费用类型 `priceType/delete`、车证 `carCert/invalid`(作废)、报馆资料 `contractorReport/setStatus`
- **密码重置(极高危)**:`buildCompany/resetPassword`(按账户ID重置)、`/build/account/none/resetPwd`
- **生成凭证**:车证 `carCert/generate`、人员出入证 `usr/updateCardCode`
- **展会增改/设默认**:`exhibition/addOrUpdate`、`exhibition/default`(设为默认展会)、`exhibition/assignPersonnel`
- **订单/支付(搭建商侧 `/build/`,本账号 401 无权限)**:`order/placeOrder`、`order/orderPay`、`order/cancelOrder`、`order/uploadRemittanceVoucher`

### 其余写操作(同样须 HITL)
- 报馆资料:`contractorReport/saveOrUpdate`、搭建商图片配置 `contractor/imageConfig/save`/`updateStatus`/`updateSort`、报馆账单 `contractor/addBill`/`save`
- 商品/费用配置:`leasedGoodsPrice/*`(batchAdd/batchShelf/edit/setHot…)、`goodsConfig/*`、`priceType/*`、`costPrice/*`、`companyBoothRelation/edit`
- 展位/展馆/展区:工作台 `workbench/hall/edit`/`allocateChargePerson`、`workbench/area/edit`、`workbench/booth/getBoothList`
- 施工图:`work-drawing/saveBoothConstructionCompleted`、`h5/work-drawing/saveBoothConstructionCompleted`
- 问题配置:`problem/save`/`update`/`batchUpAndDown`;表单配置:`form/config/edit`;展位导入:`workbench/boothImport/dataImport`
- 系统日志:`getLog/getOldLog`/`getBatchOldLog`
- 导出类(可能大体积/耗时):各处 `export`/`dataExport`/`exportExcel`(报馆、搭建商、搭建申请、费用统计、收款催款等)
- 内部 Feign(禁调):`/feign/*`(如 `builderCompany/saveBuilderCompany`、`dataSync/buildCompanyDataSync`)——内部服务间调用,非用户侧入口

### HITL 执行协议（强制）
1. **先展示、后执行**:调用前必须向用户明确展示拟发送的**精确请求**——HTTP 方法、完整 URL、请求体(body)样例。
2. **等显式确认**:用户明确说"确认/执行/可以"后才真正发出请求;不得代用户默认同意。
3. **回报结果**:执行后如实呈现响应(成功/报错/字段),不掩饰、不虚构。
4. **可撤回提示**:若写操作可能不可逆(删除/重置密码/退款),须在展示阶段提示风险,并优先询问是否有草稿/预览可用。

> 原则同 `exhibition-readonly` 的 leads 写操作(INV-5 红线):不可逆/状态变更动作不得自主执行。完整写端点清单与中文描述见 `builder_endpoints.json`。

## 重要边界

1. **只读默认开，写操作需显式确认（HITL）**：JWT 即用户本人会话，所有查询以该用户权限执行（权限标签 `permissionTag=workbench`）。只读 GET 随时可用；任何写操作（POST/PUT/DELETE）**不得由 Agent 自主执行**——须先展示拟发送的精确请求（方法+URL+body），等用户明确确认后才调用，因操作会落到真实生产账号。
2. **同源头必带**：见上，否则 401。
3. **不编造**：返回什么呈现什么；空/报错如实告知，不虚构数据或指标。
4. **令牌安全**：`MINGYANG_JWT` 含真实会话，勿写入代码/提交/日志；过期后需用户重新从浏览器复制（JWT 含 `exp` 字段，约为签发后 13 天）。

## 触发场景示例

- "查我的项目列表 / 场馆项目" → `POST /mingyang-sys/api/sys/home/orgProject/page`（params `page`、`pageSize`）
- "查角色/部门/账号管理" → `POST .../workbench/role/page`、`POST .../workbench/department/queryList`、`POST .../workbench/account/page`
- "查分类树" → `POST /mingyang-sys/api/sys/workbench/classify/queryTree`
- "单位主题配置" → `GET /mingyang-sys/api/sys/workbench/unit/getThemeConfig`
- "查施工企业/全部企业列表" → `GET /mingyang-builder/api/builder//home/private/workbench/buildCompany/page?page=1&pageSize=10&field=&sortBy=desc`（注意 `//` 双斜杠，实测 200 + 真实数据）
- "承建商报馆列表" → `GET /mingyang-builder/api/builder/home/contractor/page`（实测 200 + 真实数据）
- "项目下展会列表" → `GET /mingyang-builder/api/builder/home/h5/exhibition/getExhibitionListByProject`
- "全量展位" → `GET /mingyang-builder/api/builder/build/workbench/booth/none/getBoothList`（964KB 真实展位）
- "工作台待办 / 展位概览 / 搭建商统计" → `GET /mingyang-builder/api/builder/home/page/backlog`、`/home/page/booth`、`/home/statistic/builderStatistic`
- "车辆证件列表（需展会上下文）" → `GET /mingyang-builder/api/builder/home/carCert/page`（带默认展会即出数据）
- "展会数据同步进度" → `GET /mingyang-builder/api/builder/home/exhibition/getSyncTaskProgress`
- "查某展会的展位地图/统计" → 先 `GET .../home/h5/exhibition/getExhibitionListByProject` 取 `exhibitionId`，再 `GET .../home/booth/map/getBoothMapInfoAndBoxLocation?exhibitionId=<id>` / `.../home/booth/map/boothStatistics?exhibitionId=<id>`
- "改/审某条记录" → 先 `page/list` 取记录 `id`，再对 `detail/info/audit` 端点 **HITL 确认后**发起写请求
- "查我的报名信息 / 展商参展报名" → `GET /mingyang-company/api/company/site/exhibitor/page`（params `page`/`pageSize`，**company 站点令牌**）
- "查我的企业信息 / 证件 / 客户 / 论文集 / 个人统计" → `GET .../company/site/company/datail`、`POST .../company/site/certificate/page`、`POST .../company/site/customer/page`、`POST .../company/site/proceedings/query`、`POST .../company/site/userApplyMessage/getMyStatistics`

## 回归测试（只读能力门禁 · 三层）

**manifest 驱动、通用 harness 单份复用**：执行逻辑集中在仓库级 `tests/skill_live_check/harness.py`（非 skill，不放 `skills/`），本 skill 只维护一份声明式清单 `skills/mingyang-venue-ops/live.manifest.json`（随 skill 走）。真实调用，**默认仅 GET**；仅 manifest 显式声明的 `post_data`/`post_struct` 会发 **POST 只读查询**（对应前端 `page`/`list` 类，params 走 query string），**绝不触达任何写端点**。

三层体系（详见 `tests/skill_live_check/GOLDEN_MASTER.md`）：

| 层 | 作用 | 何时跑 | 依赖 |
| --- | --- | --- | --- |
| **L1 结构断言** | 鉴权/可达/200/有数据/写护栏（manifest 内 8 组断言） | 日常本地 | 实时接口 + 有效 JWT |
| **L2 黄金主** | 结构指纹比对，捕获 schema 漂移（归一化：TS/UUID/长数字ID→占位符，list 丢顺序/长度） | 日常本地（或 `--regen` 重录） | 实时接口 + 有效 JWT |
| **L3 气隙回放** | 读录制的 cassette，断网跑；物理杜绝误发写请求 | CI / 离线 | 不需网络（cassette 已入库） |

```bash
# 方式一：CLI 实时跑 L1+L2（默认）
python tests/skill_live_check/harness.py skills/mingyang-venue-ops/live.manifest.json
echo %ERRORLEVEL%   # 0=全过, 1=有硬失败

# 方式二：pytest 薄壳（每个集成 skill 一个 test_*.py，复用同一 harness）
python -m pytest tests/skill_live_check/ -q

# L2 重录黄金主（API 变更后；须人工 review diff，绝不静默覆盖）
python tests/skill_live_check/harness.py skills/mingyang-venue-ops/live.manifest.json --regen

# L3 录制 / 气隙回放（replay 断网也能过，最适合做 CI 门禁）
python tests/skill_live_check/harness.py skills/mingyang-venue-ops/live.manifest.json --record
SKILL_HTTP_MODE=replay python -m pytest tests/skill_live_check/ -q
```

**L1 八组断言**（manifest 内 `assertions`，失败则退出码 1）：
1. **A 鉴权**：JWT 解析且非空 + Base 已配置。
2. **B1 全局端点**（5 个）：`contractor/page`、`getExhibitionListByProject`、`buildCompany/page(//)`、`getBoothList(none)`、`pay/none/payConfig` —— 必须 http=200+code=200+有数据。
3. **B2 默认展会作用域**（6 个）：`page/backlog`、`page/booth`、`page/getBoothCompleted`、`statistic/boothStatistic`、`statistic/builderStatistic`、`h5/work-drawing/getBoothCompleted` —— 仅断言结构合法（数据随默认展会，可能为空）。
4. **C 带 exhibitionId 端点**（3 个代表）：`booth/map/boothStatistics`、`carCert/page`、`boothRemoval/page` —— 遍历 43 个展会，断言至少可达且结构合法（数据占比仅报告，免疫列表顺序不稳定）。
5. **D sys 边界（10 项）**：GET 只读（`workbench/unit/getThemeConfig`、`home/orgProject/check`、`sysOrgClient/getAccountClientAuthority`）与 **POST 只读查询**（`home/orgProject/page` 项目列表、`workbench/role/page`、`department/queryList`、`account/page`、`classify/queryTree`）均须 http=200+code=200（并比对结构）；机构级/系统管理员级端点（`org/page`、`permission/page`）=401（正常权限边界）。
6. **E 写护栏**：`write_calls=0`——harness 只会发 GET 与 manifest 显式声明的 `post_*` POST 只读查询，任何真正的写调用会触发 `SystemExit`。
7. **F.company**（8 项）：`/site` 门户只读（`site/exhibitor/page` 报名信息、`site/exhibitor/task-steps`、`site/company/datail`、`site/certificate/history/statistics` 等）须 http=200+code=200+数据结构；**使用站点令牌**（`jwt: "site"` → `.codebuddy/scripts/.mingyang_site_jwt`）。
8. **G.portal**（4 项）：`/site` 门户其余微服务只读——`/mingyang-operation/api/operation/site/audience/page`（**观众报名**，对应报名页 type==8 分支）、`operation/site/information/page`、`operation/site/invitation/queryEffectiveInvitation`、`/mingyang-public/api/public/site/classify/queryParentClassify`；同样用站点令牌。

> 新集成 skill 接入：在自身目录放一份 `live.manifest.json` + 在 `tests/skill_live_check/` 复制一个薄壳 `test_<skill>.py`（改 MANIFEST 路径）即可，**无需改 harness 代码**。
> **任务级黄金集**：`tests/skill_live_check/tasks.golden.json` + `test_complex_tasks.py` —— 把"**用户提示词 → 多端点编排**"固化成用例（断言"可达 + 响应 schema"，不锁具体值；HITL 写任务自动 `skip` 不执行）。同 live/record/replay 三模式，复用 harness 传输层与多令牌。当前 4 条任务（A 展会体检 / B 指定展会运营 / D 个人中心待办 / E 报馆批量审核[HITL,skip]）。
> 凭据解析（**多令牌**）：默认令牌优先环境变量 `MINGYANG_JWT`，否则从 manifest 目录**向上查找** `<repo>/.codebuddy/scripts/.mingyang_jwt`（workbench）；其余令牌在 `manifest.jwt_files` 里按 key 声明（如 `"site": ".codebuddy/scripts/.mingyang_site_jwt"`），断言用 `"jwt": "<key>"` 选用。令牌文件被 `.gitignore` 的 `.code*/` 覆盖，不进库，安全。过期（约 13 天）后需重新抓取。
> L2/L3 产物（均随仓库提交、不依赖实时网络）：`tests/skill_live_check/golden/`（33 个归一化指纹基线）、`tests/skill_live_check/cassettes/`（当前 80 个录制响应文件，由 `--record` 生成；同一 (方法,URL,params) 共用一条）。`--regen`/`--record` 重录后须 **人工 review diff** 再提交，绝不静默覆盖。
