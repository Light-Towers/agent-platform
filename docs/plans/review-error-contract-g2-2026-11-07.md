# 错误契约 G2 实现件 · 待审核问题清单（2026-11-07）

> 本件是**问题交接件**，不是方案件，不改一行代码。对象 = 工作区那 8 件未提交改动（错误契约 G2 的实现面）。
> 每条都给了「复现命令 + 我实测到的读数」，审核人以命令现取为准，**不要以本件文字为准**——本件文字若与命令读数冲突，以命令为真并回报本件错处。

## 0. 复现环境与前提交代

- 宿主：Windows + PowerShell（无 `make`，命令一律 `uv run …` / `node …` 形式）。
- 代码基准：HEAD = `4f21f91f`（docs-only 收口枚）；远端 `company/feat/web-visual-poc` = `d4d3d329`（现网镜像内 rev），本地 ahead = 14。
- 被审对象 = 工作区 8 件 `' M'`（staged = 0）：

```text
git diff --numstat HEAD    # 合计 +148 / -45（本件原写 -44 是我加法错，已按逐行重算订正；审核人复现的是逐行值，未复现行和）
15  1   applications/agent_federation/api/server.py
19  12  applications/agent_server/api/query_router.py
20  7   packages/agent-runtime/agent_runtime/identity_middleware.py
13  1   packages/agent-runtime/agent_runtime/schemas.py
2   1   packages/shared-schemas/shared_schemas/__init__.py
38  9   packages/shared-schemas/shared_schemas/error.py
29  0   packages/shared-schemas/tests/test_contracts.py
12  14  web/src/api/errors.ts
```

- 取证件都在 `.tmp-scratch/ap-visual/` 下（gitignored，不入库，故本件里一律用**不带反引号**的普通文本指代；要复现请跑下面命令自己重新生成，不要去找那些文件）。
- **归属：这 8 件 = ext（并行线归属），不由我提交**。实物依据两条，均已现取核过：件 k59-ext-final.txt 列的文件集与本节 numstat 逐字相同（八行一字不差）；台账 `docs/operations/evidence/2026-10-30-web-visual-references/readings.md` §53 六第 10 条原文「ext 那 8 件（并行线归属）**不由我提交**；错误契约那一簇的拍板痕迹仍未收」，§53 七原文「不强推、不硬合、不为干净而放宽任何断言或删用例」。
- **基准区分（红在哪一层必须先说清）**：提交门禁的 ruff 基准是**候选树**，门件那把（e26-gate-00-20261106-212347-gate-fill.txt）逐字为 `ruff :: rc=0 expect=0 basis=candidate-tree OK`；同件另格 `shared-worktree ruff: rc=1 errors=10 offending-files=2 not-in-ext=0` 并把那两件逐行标为 `WORKTREE-RED-FILE(ext)`，且带 `BASIS-IS-TREE-PROVEN`（tree=0 / worktree=1 两值必须不等，否则换形只是标签）。⇒ **全仓 worktree 面红 ≠ 提交门红**，本件下文所有「红」若未注明基准均指 worktree 面。

## 1. 一句话结论

这 8 件同时具备两个属性，不得只引此舍彼：**归属 = ext（不由我提交，§53 六第 10 条），射程 = G2 未批**（`docs/plans/plan-error-contract-staged-split-2026-11-06.md` L82 明写 G1 不碰这些文件，§8 明写「未批准 = G2 全部」）。两者不矛盾：前者说**谁提交**，后者说**能不能合**。⇒ 本批默认处置 = **第三档：保持原样、G2 拍板交人（D2）**，既不删也不补（逐条见 P2 复核要点）。

当前混合态（HEAD + 这 8 件）的 **worktree 面只有两处红，且同源**：联邦 session 2 failed 与全仓 ruff 10 errors —— 两者都出自同一条 G2 装配链（错误体换形 + 新符号接入），L199 / L208 是**同一换形的两处投影**，不是两个独立根因。门件基准（候选树）仍为 rc=0，见上节。

## 2. 射程核对（账面核对，逐句可在方案件里按行号读到）

`git show HEAD:docs/plans/plan-error-contract-staged-split-2026-11-06.md` 取四处原文：

- **L5（状态行，射程以此为准）**：「状态：**G1 approved / G2 proposed**。2026-11-06 用户批示「从全局治本的视角分析、解决」⇒ 按 §4 六条动手（可逆方向），G2 那批仍待逐条拍板。**批准范围 = §4，不越界到 §5**。」
- L82：**G1 明确不做**——不改 `web/src/api/errors.ts`（含 `STREAM_TEXT_KEYS` 顺序变更，属 G2 前端侧）、不改 `packages/agent-runtime/agent_runtime/identity_middleware.py` / `applications/agent_server/api/query_router.py` / `applications/agent_federation/api/server.py` / shared schema 的存量改写部分、不开任何 app 的 `normalize_http_errors=True`。
- §6 L94（另一条必须随射程一起读）：**重复实现债的复审触发条件** = 「任一 app 开启 `normalize_http_errors=True` 时，该副本（knowledge-service 自带一份 `applications/knowledge-service/knowledge_service/utils/error_response_utils.py:35`）必须先收敛到 kernel，否则那次开启的 diff 里出现第二份信封构造代码即应判红。」
- §6 L95：**形态债的复审触发条件** = 「G1 落地后 `http_exception_handler` / `_normalize_detail` / `stream_error_frame` 在默认路径下**存在但未安装**，这是有意状态不是死代码；G2 任一 app 翻 True 那一批，本条登记作废并换成逐 app 的实装读数。」
- §8：未批准 = G2 全部；G1 批准范围仅 §4 六条。

⇒ 要合这 8 件，必须先有 G2 的拍板记录。另需提醒：**L5 与 §8 有一处时态矛盾**（L5 已写 approved，§8 仍写「G1 待用户点头」）。已现取核对：§8 同句自己注过「本行原写「五条」是初版遗留，2026-11-06 就地订正」，但同一行里「G1 待用户点头」这半句未随之更新。以 **L5 为准**（用户已批 G1）；该矛盾属那份方案件自身的待订正项，**登记在此、不由我改他人文件**。

## 3. 问题逐条

### P1（阻塞）：身份中间件 5 条 401 出口换形，打断联邦两枚用例

- 实物：`packages/agent-runtime/agent_runtime/identity_middleware.py` 的 `_send_json` 由 `json.dumps({"detail": detail})` 改为 `json.dumps(error_body(code or error_code_for_status(status), msg, rid))`；5 个调用点各追加 `code=`。
- 复现：

```powershell
uv run pytest applications/agent_federation/tests/unit/test_identity_guards_order.py -q
```

- 我实测：`2 failed, 6 passed`（全目录跑为 `2 failed, 190 passed, 1 skipped`，rc=1）。失败用例：
  - `test_forged_jwt_with_correct_api_key_still_identity_401` → L208 `KeyError: 'detail'`
  - `test_forged_jwt_and_wrong_key_identity_401_wins` → L199 断言失败，捕获体为
    `{'code': 'IDENTITY_TOKEN_INVALID', 'msg': '身份令牌无效: 令牌格式非法: Invalid crypto padding', 'request_id': 'cb3dfb7aa6b0'}`
- **请重点审 L199 那枚**：原文是 `assert "code" not in body`，注释写明判据语义 = "guards 的错误信封是 `{\"code\": \"UNAUTHORIZED\", ...}`；身份层是 `{\"detail\": ...}`"，即用"是否带 code"来区分**这发 401 由哪一层答的**（接线序回退探测器）。中间件也开始发 `code` 后，该条件不再具备区分力——这不是断言太严，是判据被换形动作消解。
- 【原待答，现已有判语】修法只能是"换更强的判据"而非删断言（红线：禁止为过测试放宽断言）。候选 = 按 `code` 取值区分（guards 发 `UNAUTHORIZED`，身份层发 `IDENTITY_*`）。**审核人已判：不等价**（判语全文见 §7 第 2 条）。修法 = 补显式的层归属信号 + 反证用例，**不得删、不得放宽这条断言**；该项属 **G2 拍板后的下一刀**，不列本批待办。

### P2（阻塞）：全仓 lint 唯一红源是联邦件的半成品接线

- 复现：

```powershell
uv run --with ruff ruff check .
```

- 我实测：`Found 10 errors`（rc=1），按文件分组 = `applications\agent_federation\api\server.py` 9 枚（1 枚 I001 导入块未排序 + 8 枚 F401 未用导入：`AppError` / `SANITIZED_5XX_MSG` / `make_error_response` / `mask_exception_for_client` / `stream_error_frame` / `generate_request_id` / `get_request_id` / `set_request_context`），`applications\agent_server\api\query_router.py` 1 枚（F401 `fastapi.HTTPException`，5 处 raise 已全部换成 `AppError` 后遗留）。
- 推断（**这条是推断，不是读数**）：那 8 个未用 import 的真实意图指向同件的 WS 错误帧 —— 行号按两基准都注：**HEAD L431 / 工作区 L445**（同件另有 HEAD L405 / 工作区 L419 一枚同形状帧；行号须注基准，这条订正见 §4 第 2 条）

```python
await websocket.send_json({
    "type": "error",
    "error": f"Internal error: {type(e).__name__}",   # 旧键 + 异常类名直出，未脱敏
    "thread_id": ws_thread_id,
})
```

  即"准备收进统一流内错误帧，改到 import 就停了"。请审核人核实这个归因，或给出别的意图。
- 复核要点（**按审核第一条订正：原写「两种处置」是伪二选一**）：实物上至少三档，且第三档才是本批默认档——
  1. 只删 import（退回 HEAD）：把半成品接线撤掉，代价是丢掉并行线已写下的意图；
  2. 补完改造：把 WS 两帧收进统一流内错误帧，属 G2 射程内的实装；
  3. **保持原样、G2 拍板交人（D2）**：不删不补，8 件原样留在工作区，由 G2 的批准记录决定去留。

  审核判语：1 与 2 都以「我这轮有权动 ext」为前提；而**归属 = ext**（§0）与**射程 = G2 未批**（§2）两条同时成立 ⇒ 该前提不成立，前两档都不是我能执行的处置，**本批按第 3 档执行**。

### P3：新增的 `x-trace-id` 响应头，全仓测试面零断言

- 实物：`_send_json` 的响应头新增 `(b"x-trace-id", rid.encode())`（只覆盖身份中间件的错误路径；成功路径未发，与在册挂项 day-2「是否补 x-trace-id 后端装配」一致）。
- 复现（期望 rc=1，即测试面零命中）：

```powershell
git grep -rn "x-trace-id\|X-Trace-Id" -- 'tests' 'applications/*/tests' 'packages/*/tests'
```

- 我实测：rc=1（零命中）。含义 = 这是一个**横切关注点的单一实现 + 全局装配已动、强制门禁缺失**（AGENTS.md《架构决策原则》三层缺一层）。请审核人判它是否该在合入前补一枚行为断言。（按审核四②：这属 **G2 拍板后的下一刀**，不列本批待办。）
- **负例必须配正对照**（否则"零命中"可能只是模式写坏或路径限定失效）。同一 pattern 放宽到全仓：

```powershell
git grep -rn "x-trace-id\|X-Trace-Id"
```

  我实测：有命中（`applications/agent_server/api/auth_router.py:10` 的注释、knowledge-service 的 README/CHANGELOG/代码多处）⇒ 模式本身能咬到东西，"测试面零命中"是真的零命中，不是量具空转。审核人可用这两条对拍。
- 附带事实：knowledge-service 侧早有一套 `X-Trace-Id`（`applications/knowledge-service/knowledge_service/api/errors.py:39-42`），大小写与注入方式与本件不同；两条链是否要求同形，属于 G2 契约决策。

### P4：`VALID_ADMISSION_REASONS` 是零消费的装饰性常量

- 复现：

```powershell
git grep -n "VALID_ADMISSION_REASONS"
```

- 我实测：只命中定义行 `packages/agent-runtime/agent_runtime/schemas.py:27`。`AdmissionReason`（Literal）本身有消费（同件 L37 收窄 `reason` 字段），frozenset 没有任何用例或门禁引用。
- 待答（按审核四②标为**下一刀**，不列本批待办）：要么装一枚消费点（用例断言 Literal 项集 == frozenset，防两处漂移），要么删。**保留而不消费**在本仓按"装饰性齿"处理。
- 顺带给出我核过的安全性（这项**不是问题**，是已证伪的风险）：收窄 `reason` 后，HEAD 生产方只发 4 枚字面值，全在新集合内：

```powershell
git grep -n 'reason="' -- '*.py' | Select-String -NotMatch 'RATE_LIMITED|ADMISSION_UNAVAILABLE|ADMISSION_TIMEOUT|ADMISSION_REJECTED'
```

  我实测：零命中（rc=1）⇒ 没有集合外的生产者，pydantic 不会在构造期炸。正对照 = 去掉那个 NotMatch 管道，同一条命令命中 4 行（均在 packages/agent-runtime/agent_runtime/admission.py，值分别为 RATE_LIMITED / ADMISSION_UNAVAILABLE / ADMISSION_TIMEOUT / ADMISSION_REJECTED）。

### P5：`msg` 字段的承诺与实际内容矛盾（HEAD 既有，非本簇引入）

- 实物：`packages/shared-schemas/shared_schemas/error.py` 新增的 `ErrorEnvelope.msg` 声明为"已脱敏的人类可读错误描述"；而中间件调用点传的是 `f"身份令牌无效: {e}"` / `f"内部签名头无效: {e}"`，`{e}` 会带出库内部文本（实测样例 `Invalid crypto padding`）。
- 我核过：`{e}` 插值在 HEAD 已存在，本簇只追加 `code=` —— **不得把这条记成本簇新引入**。但它原先住在 `detail`、现在住在"承诺已脱敏"的 `msg`，语义等级变了。
- 上屏实测（三条，用现有 `describeError` 跑真体，件 k79-identity-401-screen.txt）：

```text
EXT体-经EXT解析   => 身份令牌无效: 令牌格式非法: Invalid crypto padding（request_id cb3dfb7aa6b0，请凭它查服务端日志）
EXT体-经HEAD解析  => 身份令牌无效: 令牌格式非法: Invalid crypto padding（request_id cb3dfb7aa6b0，请凭它查服务端日志）
HEAD体-经HEAD解析 => 密钥未填或不正确（服务端：身份令牌无效: 令牌格式非法: Invalid crypto padding）
```

## 4. 我这轮订正掉的三条在册判断（审核人若沿用旧文会判错）

1. **「前端 errors.ts 必须与后端同枚绑定」——不成立。** 上面第 2 行读数证明：HEAD 版前端已能解析新信封（两行输出逐字等价）。补充实物依据：

```powershell
git diff --numstat d4d3d329 HEAD -- web/src/api/errors.ts    # 我实测：空输出 ⇒ 现网 rev 与 HEAD 同版
git show d4d3d329:web/src/api/errors.ts | Select-String 'typeof o\.msg'   # 我实测：命中 ⇒ 现网前端已在读 msg
```

2. **方案件 §5 第 3 条「`STREAM_TEXT_KEYS` 换序今天没有实测」——已补成实测，且结论是"今天无影响"。** 双键同帧时 EXT 出 `msg`、HEAD 出 `error`；但今天**没有任何一帧同时带两键**（带 `error` 键的只有联邦 WS 那两帧，帧内没有 `msg`；原写"没有生产者同时发两键"措辞不准，订正见本节末）。⇒ 它是双写窗口开启后的前置风险，不是今天的缺陷。这条把方案件里那条 D2 的紧迫性降低。下面那条 grep 的口径缺陷、以及我原先"无生产者"这个措辞，均在紧接的订正里改掉：

```powershell
git grep -nE '"error":' -- '*.py'
```

  订正（按审核第三条，一处措辞 + 两处量具口径）：
  - 上面那条 grep **只认双引号字面键**，单引号形态整体漏扫。补跑同 pattern 的单引号版：

```powershell
git grep -nE "'error':" -- '*.py'
```

    漏扫命中 1 处：`tests/governance/test_exception_echo_governance.py:113`（fixture 里的 `{'body': {'error': str(exc)}}`）。
  - 且双引号那把的命中里，带 `error` 键的**帧有两枚不是一枚**（原写「只有 :431 一处」错）；行号必须注基准：HEAD L405 / L431，工作区 L419 / L445（import 块 +14 行整体下移）。
  - ⇒ **原措辞“无生产者”作废，收窄为“同一帧内无双键”**，依据换成有界枚举（不再靠上面那条 grep）：发 `msg` 的构造器只有两枚，都在 `packages/agent-core/agent_core/guardrails/errors.py` —— `error_body`（L132-142，键为 code、msg、request_id、details）与 `stream_error_frame`（L145-163，键为 type、code、msg、request_id、details），两者都不可能产出 `error` 键。`stream_error_frame` 的真实调用点在 `applications/agent_server/api/query_router.py` L379，专测在 `tests/api/test_query_error_sanitization.py` L108（`test_stream_error_frame_is_sanitized`）。⇒ 结论“今天换序无影响”不变，但它是从**同帧无双键**推出来的，不是从“无生产者”推出来的。
  - **残余盲区（只登记、不封）**：上面 = 同一行 grep + 两个构造器穷举，未穷举“手写多行 dict 同时写两键”这种形状。本轮不加齿（§53 〇 停止一切新增），要封这条请在拍板后的下一刀处理。
3. **「held 成因是它们依赖并行线尚未入库的符号」——已不成立（上轮入库时订正过，本轮再证）。** 这簇用到的符号在 HEAD 全齐：

```powershell
git grep -n "error_body" HEAD -- packages/agent-core/agent_core/guardrails/errors.py   # 命中 4 行；下列同法
```

  我实测命中行数：`error_body` 4 · `error_code_for_status` 4 · `AppError` 10 · `SANITIZED_5XX_MSG` 6 · `make_error_response` 7 · `stream_error_frame` 3 · `mask_exception_for_client` 3；`agent_core/tracing.py` 的 `generate_request_id` / `set_request_context` / `get_request_id` 均有 def 定义行。
4. 形状细节：`identity_middleware.py` 工作区版 EOF 多一枚空行（HEAD 止于 `self._reset(tokens)`）；`git diff` 对 `identity_middleware.py` 与 `web/src/api/errors.ts` 报 CRLF→LF 警告，入库时会被 `.gitattributes` 归一，别把归一后的行数当成 diff 行数。

## 5. 未受影响的面（给审核人划出"本轮跑过且没动"的范围；它不等于"已验证"，表外两格见下）

| session / 门禁 | 读数 | rc |
|---|---|---|
| tests/governance | 521 passed, 1 skipped | 0 |
| packages/agent-runtime/tests | 888 passed, 2 skipped | 0 |
| applications/agent_server/tests | 183 passed | 0 |
| packages/shared-schemas/tests | 31 passed | 0 |
| node web/scripts/check-events.mjs | 端点成对性 消费 5 / 提供 22 / 缺 0 | 0 |
| node web/scripts/verify-sse.mjs | 合计 150 条断言，失败 0 | 0 |
| web typecheck（vue-tsc --noEmit） | 无输出 | 0 |
| scripts/lint_architecture.py | L-5 / P13 / L-1 / L-2 / L-4 / P14 全通过 | 0 |

**本表故意不含的两格**（按审核第五条补，防本表被读成“全面已验”）：

- `applications/agent_federation/tests/unit/test_identity_guards_order.py` —— **唯一真红**（2 failed / 6 passed，P1）。它属“受影响的面”，不在此表口径内。
- 提交门件 e26 全套 —— **本轮未跑**（见 §6）。它最近一轮的候选树 ruff rc=0 是**上一轮的件**说的**上一轮的面**，不覆盖本轮（AGENTS.md 取证规矩第 9 条：判决新鲜度）。

注：`tests/governance` 全绿说明**没有任何用例在钉身份中间件 401 的响应体形状**（否则早就红了）——P1 的测试面只有联邦那两枚。这既是"改动影响面小"的证据，也是"缺默认不变量保护"的证据，两种读法都成立，请审核人表态该按哪种。

## 6. 本轮**未跑**（不得读成已验证）

门件 e26 全套 · ts-provability · 变异战役 · `make ci-web` · 全量十 session · `lint_public_mirror.py` publish 面 · 现网任何一格（服务器通道不可达，在册）。

## 7. 六个问题（1、2 已答；3–6 **待人拍**——审核判语已给，但“要不要做”不是审核人能定的；且按四②属下一刀）

1. G2 的批准是否已在别处达成？若没有，P1/P2 的处置（补完 vs 退回 HEAD 的联邦件）算哪一档决策？ **〔已答〕** G2 未达成 ⇒ 先拍板、不动 ext；本批走第三档（保持原样，D2），所提的“补完 / 退回”两档都不是我能执行的处置。
2. `test_identity_guards_order.py` L199 的判据换成"按 `code` 取值区分"，是否等价覆盖"接线序回退探测"的原意图？
   **〔已答·不等价〕** 原判据用的是“只有 guards 信封带 `code`”这一**形状差**来回答“这发 401 由哪一层答的”；改成按 `code` 取值区分，等于把判据从“有没有这个键”降级为“这个键是什么值”，第三层一旦也发 `IDENTITY_*` 之外的值就重新失去区分力。等价修法 = **补显式的层归属信号 + 反证用例**（把接线序故意改错，用例必须红），且**不得删 / 不得放宽这条断言**。本项属 G2 拍板后的下一刀。
3. 身份层 5 条 401 的对外形状变更，消费者清单谁负责审？（我只查到前端已兼容 + 联邦两枚用例；其余消费者我没能穷举。）
4. `{e}` 直出库内部文本进 `msg`，按本仓脱敏口径算不算必须收的项？收的话是改调用点还是改 `ErrorEnvelope` 的字段承诺？
5. `x-trace-id` 是否要求成功路径同发（在册 day-2 挂项），以及与 knowledge-service 那条 `X-Trace-Id` 是否必须同形？
6. `VALID_ADMISSION_REASONS` 装消费点还是删？

## 8. 审核回应六处的落地对账（2026-11-07）

| 审核条 | 落地位置 | 改动性质 |
|---|---|---|
| 1 归属=ext + 第三档 | §0 归属条 · §1 尾句 · P2 复核要点 | 账面：伪二选一改三档，默认第 3 档 |
| 2 候选树 ≠ worktree 基准 | §0 基准区分条 · §1 中句 | 账面：所有“红”注明所在层 |
| 3 量具只认双引号字面键 | §4 第 2 条 · P2 推断行 | 账面：“无生产者”收窄为“同帧无双键”，依据换有界枚举，登记残余盲区 |
| 4 补引 L5 与 §6 L94/L95、修时态矛盾 | §2 四处原文 + 末段登记 | 账面：以 L5 为准，他人文件不由我改 |
| 5 表格改名 | §5 标题 + 表外两格 | 账面 |
| 6 P1/P2 同源 | §1 中句 | 账面：两处红归到同一条 G2 装配链 |

**两手自清（审核四条）**：

- 四① 本件至今是未入库的 `??` 面。**用户已拍：选 C——先不动，等 G2 拍板那一批一起入**（三条理由：第 11 条此刻不激活，真必须入库的是拍板记录；A/B 都卡在“提交前须复跑门件”同一个前置，而 §53 〇 不重开评估面；第 12 条指向 C——现在入库不会让任何判据读到它，不增加覆盖）。⇒ 到拍板那一批，把“拍板记录 + 六处订正 + Q3–Q6 结论”一次性誊进已入库台账 `docs/operations/evidence/2026-10-30-web-visual-references/readings.md`（即 B 的实质），门件复跑本就是那批提交的前置，不额外多一轮。
- “保留待判”的**复审触发条件**（《分支卫生》第 2 条：无触发条件的登记不许写；**任一命中立即复审、按 B 落账、同批复跑门件、用精确 git add 而不是 add -N**——§53 一那个“把申报当入库”的坑）：① G2 任一 app 拍板（方案件 §6 L95 本就以它为触发）；② 本件被任何**入库文档**按件名引用（那一刻它才成为批准依据）；③ 本件要作为 L3 / 推送前置的输入；④ 会话交接、换机或清理 `??` 工作区。
- 四② 本件原先提的“补层归属信号 / 装消费点 / 换判据 / 补 x-trace-id 断言”已逐项标为 **G2 拍板后的下一刀**（见 P1 / P3 / P4 / §7），不列本批待办；本轮未新增任何判据、量具或断言。

**边界（与审核人一致）**：本轮只改这一件我自己创建的文档；未动那 8 件 ext 任何一字节、未提交、未推送、未部署；现网 rev 仍 d4d3d329，服务器通道不可达。

**本轮末尾两处自纠（不等人指出）**：

- §0 行和 `+148 / -44` → `+148 / -45`：逐行 numstat 的删除列相加 = 45。审核回应里引用的也是 `-44`（沿引本件），逐行值两边一致 ⇒ 错只在我的行和。审核人当场认下“他们上一回也在沿引 -44、同样没复算行和”⇒ 这一笔双向各记，不只是我这边的错。
- 面禁件的一个口径事实：默认面 = **17 件入库件**（跑的是入库那把 scripts 下的 typo-scan），本件是 `??` 未入库，**不在那一面里** ⇒ “默认面那枚退出码为零的读数”不能当本件形状干净的证据（该件不打印退出码键，故此处按件的打印形状书写，不写成裸键）。已另跑一次同脚本的既有旋钮 -FilesOverrideCsv 指向本件自扫（读件 k80-typo-selfscan3.txt）：T1 hits=0、T2 hits=0、T3 hits=0、T4 hits=0、T5 hits=0、码点 forbidden=0（均为件内逐字键形；该件不打印退出码，退出码 0 是运行时读数不入件）。这一型就是 AGENTS.md 取证规矩第 12 条“入库 ≠ 被读”的反向用（未入库 ⇒ 根本没被读）。

**读数补记（审核回信带来的“面数 17 vs 16”分歧，已复现并定性）**：

- 复现读数：入库那把 scripts/evidence/typo-scan.ps1 = **194 行 / 11,774 B / mtime 11-06 21:01:54 / tracked**；本机副本 .tmp-scratch/ap-visual/typo-scan.ps1（不在清单内，故用普通文本写）= **188 行 / 11,136 B / mtime 11-06 17:45:41 / 未入库**。两份的面表差值 = 刀 k76 进面的 `docs/adr/0010-ui-stack-selection.md`（面表 +1 行 + 5 行进面依据注释）。
- **定性：这不是新的漂移，是第 12 条在册那一型的同一对实物**——194/17 vs 188/16 早已登记，门件件 e26-gate-fill.ps1 L37 的注释原文就写着这两个数（本轮现取）。⇒ 审核人开的处方（“默认面 rc=0 必须绑脚本路径”）对**门件侧已生效**：同件 L43 把调用点钉在入库路径（刀㊵ 五个消费点重指已落地）；残余面只剩**手工跑件**——本轮我这把读数就是跑的入库份，本件自扫那三格亦然，已逐格绑路径。
- 不加新齿（§53 〇）：本条只把口径写进读数，不新建“必须绑路径”的判决。复审触发条件沿用第 12 条在册那条（再出现一次“改了入库件而门件读数不变”，或新建一代门件）。
