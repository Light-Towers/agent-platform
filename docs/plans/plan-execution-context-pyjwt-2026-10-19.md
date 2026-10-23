# ExecutionContext 迁 PyJWT + 标准 JWT（#85）

- 日期：2026-10-19
- 来源：GitHub issue #85 / TODO §0.2 C 组第 1 条（拍板对象 = exhibition-agent 契约版 `ExecutionContext`）
- 类型：手写密码学 → 标准库收敛（wire 兼容，非契约变更）

## 1. 取证摘要（#85 已立，命令与计数可复跑）

| 项 | 结论 |
|---|---|
| 拍板对象 | `exhibition_agent/contract/execution_context.py:36`（pydantic 7 字段，无凭据）；**勿混**同名异物：`agent_runtime/planner/protocol.py:216`（预算/lease）与 foundation dataclass 版 |
| 消费者面 | 仅 exhibition-agent 内（构造 5 / 读字段 4 / state 传递 2）；ks/kefu/nl2sql 零命中；跨进程仅 HTTP header `X-Execution-Context`，下游 warehouse 透传复验；无 WS/SSE 路径 |
| 手写实现 | `middleware/context_codec.py`：手写三段 base64url + 手写 HS256 HMAC（docstring 明写「不引入 pyjwt」） |
| PyJWT 先例 | agent-runtime 已有 `PyJWT[crypto]>=2.9`（`identity.py` RS256 + fail-closed + 单测）；红线「PyJWT 不进 agent-core」（ARCHITECTURE.md:63）⇒ exhibition 引入合规 |

## 2. 三个待方案问题的回答

1. **HS256 保语义，不迁 RS256**：exhibition 的秘密是配置注入的共享密钥（`F01_SIGNING_SECRET`/`jwt_secret` 形参），与 agent-runtime 的 RS256+kid 轮换体系是不同生态；迁 RS256 需引入密钥轮转基础设施，超出「手写→标准库」收敛范围。wire 本就是 JWT 形状 ⇒ HS256 保持即线上兼容。
2. **alg=none mock 分支用 PyJWT 原生表达**：`jwt.encode(payload, key=None, algorithm="none")` 实测产出与手写版**逐位同形**（空第三段、无 warning）；DEV 档不验签路径经 `options={"verify_signature": False}` 表达（实测无需传 algorithms、无 warning）。
3. **兼容窗口：不需要**（wire 逐位兼容）；但**验签边距逐条对码**见 §4。

## 3. 改动清单

1. `applications/exhibition-agent/pyproject.toml`：dependencies 加 `pyjwt[crypto]>=2.14.0`（与根/agent-runtime 现锁同下界；L-4 不跟踪 pyjwt，但保持仓内一致）。
2. `middleware/context_codec.py` 重写 `decode_jwt`/`encode_jwt` 为 PyJWT 实现：
   - 签名与 kwargs 不变（`verify_signature: bool` / `secret: str | None`）⇒ 中间件与测试零改；
   - 错误消息保持既有中文文案（中间件把它们透传进 401 body，属对外契约）：`"verify_signature=True 但 secret 未提供"` / `"JWT 签名无效"` / `"JWT 结构非法：期望 3 段，实际 N 段"` / `"JWT payload 解析失败：…"` / `"JWT payload 必须是 JSON object，实际 …"`；
   - `decode_base64`/`encode_base64`（适配器选项 a）不动——与 JWT 无关。
3. 新增负样本测试（手写版结构性缺失的面）：
   - **alg 混淆**：把 HS256 token 的 header 改 `alg=none` 后过 STRICT ⇒ 必须拒（PyJWT `algorithms=["HS256"]` 钉死 ⇒ `InvalidAlgorithmError` → "签名无效"）；
   - 畸形段数 / 非 dict payload（decode 侧 isinstance 守）；
   - `InsecureKeyLengthWarning` 不 suppress（短密钥告警是真实信号，测试噪声可接受；仓内无 `filterwarnings=error` 配置，实测）。

## 4. 行为保持矩阵（逐条对码）

| 行为 | 手写版 | PyJWT 版 | 判定 |
|---|---|---|---|
| 3 段结构非法 | ValueError「JWT 结构非法：期望 3 段，实际 N 段」 | `DecodeError` ⇒ 转 ValueError 同文案 | 保持 |
| payload 非 JSON | ValueError「JWT payload 解析失败」 | 同（转写） | 保持 |
| payload 非 object | ValueError「JWT payload 必须是 JSON object」 | decode 返回非 dict 时同文案 raise（encode 侧 PyJWT 直接 TypeError，比手写更严，mock 生成路径不受影响） | 保持（decode 侧） |
| DEV 不验签解析 | 手动 base64url+json | `options={"verify_signature": False}` | 保持 |
| STRICT 验签通过 | HMAC-SHA256 compare_digest | `algorithms=["HS256"]` | 保持 |
| STRICT 篡改/错钥 | ValueError「签名无效」 | `InvalidSignatureError` ⇒ 同文案 | 保持 |
| STRICT + alg=none token | 手写版**把空签名段当签名比对** ⇒ 必失败（compare_digest 对空 bytes 与期望 digest 不等）⇒ 同样拒 | `InvalidAlgorithmError` ⇒ 同文案「签名无效」 | 保持（且理由从"碰巧不等"变为"钉死算法"） |
| STRICT 无 secret | ValueError「secret 未提供」 | 显式前置检查保持 | 保持 |
| **exp 声明** | **完全不看**（潜在缺陷：过期 token 也放行） | 默认校验 exp ⇒ **显式 `verify_exp: False` 保持现状** | **保持 + 登记缺口**：过期语义未实现属契约空白（v1.1 §C1 无 exp/leeway 规定）。启用须先出契约 v1.2（exp 必填/leeway/时钟源）再改代码，**不在本项悄咪咪开** |
| aud/iss/nbf | 不看 | 不传 audience ⇒ aud 不校验（PyJWT 语义）；nbf 默认校验但 payload 无该字段 ⇒ 无行为 | 保持 |
| 短 HMAC 密钥 | 无告警 | `InsecureKeyLengthWarning`（<32B） | **新增告警（增益）**：真实信号，不 suppress |

## 5. 验收判据

- `test_jwt_signature.py` 7 条**断言逐字不改**全绿（roundtrip/篡改/错钥/无 secret/STRICT 拒无签名/STRICT 通过）；
- `test_c1_execution_context.py` + `test_server.py` 全绿（中间件与端到端路径零改）；
- 新增负样本全绿；`grep -c "hmac\|hashlib" context_codec.py` = 0（手写密码学清零的自证）；
- exhibition session 全绿不减分；ruff 全绿；docsync rc=0；
- TODO §0.2/§6 销项（open 27→26）。

## 6. 回滚

单 commit 完成（pyproject + codec + 测试），`git revert` 整体回退；wire 兼容 ⇒ 回退后手写版仍能解 PyJWT 版签的 token（HS256 标准 JWT）。
