# web/ 视觉层参照取证与对比度实算（2026-10-30）

**定位：** 证据记录（不是方案）。格式遵循 `docs/operations/evidence-format.md` §1 五字段 + §3 强度分档；新增探针的非空转反证按 §4。
**服务对象：** `docs/plans/plan-web-visual-design-2026-10-30.md`（工单件 §13.1 六格的答卷）。本件只放**读数与出处**，判断与取舍留在方案里，免得两处漂（工单件 §11.4 记过「已入库文档指向仓内不存在的路径」这型事故，所以本件里每条外部路径都配了取到它的命令）。
**读数绑定 rev：** `d140f91f`（分支 `feat/nl2sql-ttl-and-006-slim`），本批改动全部落在 `docs/` 下（四个文件动作），后端目录对该 rev 的差异为**空**（自证命令与读数见 §10）⇒ 后端读数即该树。同日**第四批**（C 路取证，见 §11）HEAD 仍 = `d140f91f`，同样**零产品代码**，所以 §1–§6 的读数不需重取。
**取数日期：** 2026-10-30（外部资源 = 当日 `gh api` / `npm view` 现取，非引二手博客；换 rev 或换月份需重取）。
**前置（字段 5）：** `gh` 2.67.0 已认证（account `Light-Towers`）、`npm` 可达 registry.npmjs.org、`uv run --no-sync`。外部读数全部依赖**公网可达**；内网机器上取不到时，本件按「标准环境已验证」档引用，不得升格为「现网已验证」。

---

## 0. 结论摘要（项 | 命令 | 读数 | 判定）

| # | 项 | 读数 | 判定 |
|---|---|---|---|
| 1 | 坐标免检（后端是否被视觉批以外的事动过） | `3868023c..d140f91f` 的后端目录差 = **仅 `scripts/evidence/recount_todo_index.py`** | ✅ 与工单件取证件预期一致 ⇒ 41 条坐标不需重取 |
| 2 | SSE 事件全集 | 派生式实取 **12 类**（Literal 8 ∪ 实现下发 12） | ✅ 设计件的分色表按 12 排，**不写死数**（门禁派生） |
| 3 | `/health` 字段全集 | 基类 **13** + 子类 **17** = **30**（无重名） | ✅ 灯阵 5 组恰好覆盖，见 §5 |
| 4 | 字体许可 | `IBM/plex` `LICENSE.txt` = `OFL-1.1`，版权行含 `Reserved Font Name "Plex"` | ✅ 许可义务可落地（方案 §1.4） |
| 5 | 字体体量 | 六件 Latin1 woff2 实测 **122,488 B**（单件 17.5–22.3 KB） | ✅ 可入库；方案里那句「≈115KB」是按 KiB 逐项四舍五入后相加得到的，**已订正为 122,488 B**（本件 §2 是准数） |
| 6 | `@ibm/plex` npm 整包 | `unpackedSize 186,600,620` / `fileCount 10,308` / `postinstall ibmtelemetry` | ✅ **否决成立**，读数见 §3 |
| 7 | Radix Colors 令牌结构 | `src/` 五个文件：`light.ts 58,664` `dark.ts 58,393` `blackA.ts 993` `whiteA.ts 1,065` `index.ts 101`，许可 `MIT` | ✅ 「同键双主题 + alpha 独立令牌」是可实取的**实现形状**，色值一个没搬 |
| 8 | 全部对比度 | 92 行读数（§6），含 8 处 `FAIL` | ✅ 三处 `FAIL` 直接改写了设计规则（见 §6「实算带出的四条结论」） |
| 9 | Jaeger UI / Langfuse trace 视图 | **已取证**（本窗口 `gh api` 现取）：Jaeger Apache-2.0（`vars.css` 10,575 B 集中令牌 + `SpanTreeOffset.css` 三通道层级），Langfuse NOASSERTION 混合许可（Next.js SSR + Tailwind） | ✅ 未推翻任何设计值，**补强 §1.2/§1.3/§2.1/§2.2/§2.3 五条**；读数与三判据回答见 §7。**订正**：上一版误将本格写为“未取证”，且误称 Langfuse 为 MIT（实取 NOASSERTION/Other） |
| 10 | V1–V7 视觉验收 | **一条读数都未取** | ⚠ 无 `web/` 可跑；本批零产品代码（见 §8） |
| 11 | 本批自查门禁（doc-sync / ruff / 后端零改动 / 引用边） | `check_doc_sync.py` rc=**0**、`ruff check .` rc=**0**、后端目录 diff 行数 **0**、`docs/` 引用边自查**全命中** | ✅ 读数与**覆盖面告警**在 §10（`check_doc_sync` 根本不扫 `docs/` 下的路径引用，rc=0 不等于引用边已证）；第三、四批的逐值复跑台账在 **§10.1 / §10.2**（第四批扩到**八道**，八道逐值与第三批相同 ⇒ 本批新增 0 条引用边） |
| 12 | C 路取证：Radix 中性族数值表 + VitePress 令牌/排版件 | Radix Colors 实取 `MIT` / stars **1,725** / 全仓仅 **22 条目**，四张中性 12 档 hex 逐字抄回；VitePress 实取 `MIT` / stars **18,446** / 全仓 `.css` **13 件**，`vars.css` **649 行**（`--vp-c-` ×227）+ `vp-doc.css` **627 行** | ✅ **借纪律不借 hex**（四条纪律 + 一条形状在 §11.5）；许可合法，“不搬”是**判据**决定的 |
| 13 | 中性色成族性实算 + Radix 候选替换的对比度重算 | light **8 枚里 7 枚在蓝相带**（唯一越带 = 纯白 `C=0`，不构成破族）/ dark **8 枚里 7 枚在带**（唯一越带 = `--text-1` 差 **2.3°**）/ Radix `dark-slate8` 勾控件边界 = **2.58 < 3.0 FAIL** / 底色差 **1.03**（light）与 **1.16**（dark） | ⚠ **两条证伪**：① 「中性色加微染」的口头建议**作废**（已在带）；② Radix 表**不能整族照搬**（会塌 SC 1.4.11）。本批唯一改动设计件正文的结论 = 「分层不靠底色差」从 dark 专属**升为两主题通用**，读数与算式见 §11.4 |

---

## 1. 坐标免检与两个派生集的复验

**命令**（rev `d140f91f`）：

```bash
git rev-parse --short HEAD
git diff --name-only 3868023c..d140f91f -- applications/ packages/ scripts/ Makefile .github/workflows/ Dockerfile .dockerignore ARCHITECTURE.md CHANGELOG.md
```

**读数**：`d140f91f` / `scripts/evidence/recount_todo_index.py`，rc=**0**（1 行输出）。
**口径**：路径过滤器沿用取证件 `docs/operations/evidence/2026-10-30-frontend-preflight/readings.md` §口径的那一条（后端 + 构建面 + CI 面），起点 `3868023c` 钉死、不用相对锚（台账 §4 **C8**：`HEAD~1` 这类锚在下一批提交后就不是同一件事）。
**结论**：视觉批不需要重取 41 条坐标；那条 `recount_todo_index.py` 是取证辅助脚本，不属被前端消费的实现。

**命令**（派生集，脚本全文在本节末）：

```bash
uv run --no-sync python .tmp-scratch/ap-visual/derive_sets.py
```

**读数**：

```
StreamEventType Literal（8）: ['route', 'evidence', 'memory', 'answer', 'error', 'status', 'replan', 'suspended']
实现里实际下发的 type（12）: ['admission', 'answer', 'cache_hit', 'coordination', 'done', 'error', 'evidence', 'memory', 'replan', 'route', 'status', 'suspended']
==> 事件全集（12）: ['admission', 'answer', 'cache_hit', 'coordination', 'done', 'error', 'evidence', 'memory', 'replan', 'route', 'status', 'suspended']

共享基类字段（13）: ['status', 'version', 'dependencies', 'storage', 'llm', 'search', 'sql_backend', 'coordination', 'admission', 'revert', 'otel', 'otel_status', 'mcp']
agent_server 子类字段（17）: ['scheduler', 'control_plane', 'cost_governance', 'forensic', 'embedding_backend', 'embedding_real', 'planner', 'guard_enabled', 'nl2sql', 'langfuse_enabled', 'langfuse_ready', 'cache_backend', 'cache_ready', 'cache_degraded_reason', 'cache_stats', 'auth_enabled', 'identity_mode']
==> /health 字段全集（30）: ['status', 'version', 'dependencies', 'storage', 'llm', 'search', 'sql_backend', 'coordination', 'admission', 'revert', 'otel', 'otel_status', 'mcp', 'scheduler', 'control_plane', 'cost_governance', 'forensic', 'embedding_backend', 'embedding_real', 'planner', 'guard_enabled', 'nl2sql', 'langfuse_enabled', 'langfuse_ready', 'cache_backend', 'cache_ready', 'cache_degraded_reason', 'cache_stats', 'auth_enabled', 'identity_mode']
```

**口径**：事件集 = `StreamEventType` Literal ∪ 实现里以 `"type": "x"` / `type="x"` 形态下发的字面量（后者覆盖 `admission`/`coordination`/`cache_hit`/`done` 那四类**不经 Literal 的直发事件**，所以只读 Literal 会得到 8 而不是 12 —— 这正是「写死 12」为什么必须换成派生式的原因）。字段集 = 两层 `HealthResponse` 的 `AnnAssign` 目标名并集（子类同名字段不重复计）。
**探针位置**：`.tmp-scratch/ap-visual/derive_sets.py` —— **本机文件，不入库**（`.gitignore:61` 的 `.*/` 规则）。本件把脚本全文贴在下面，所以「有命令、无脚本」那个形状不成立，也不触发台账 **D26** 那格（判据本体在文字里，任何机器照抄即可复跑）。

```python
"""从源派生「SSE 事件全集」与「/health 字段全集」（不写硬常数）。

这是 web/scripts/check-tokens.mjs 断言 6 的 Python 侧同形探针：期望集只从实现里读，
不在本件（也不在任何文档）里写死「12」或「30」。

用法：uv run --no-sync python .tmp-scratch/ap-visual/derive_sets.py
"""

import ast
import re
from pathlib import Path

ROOT = Path(".")
PROTOCOL = ROOT / "packages/agent-runtime/agent_runtime/planner/protocol.py"
ROUTER = ROOT / "applications/agent_server/api/query_router.py"
BASE_HEALTH = ROOT / "packages/shared-schemas/shared_schemas/health.py"
APP_HEALTH = ROOT / "applications/agent_server/schemas.py"

# ① StreamEventType Literal
proto = PROTOCOL.read_text(encoding="utf-8")
m = re.search(r"StreamEventType\s*=\s*Literal\[(.*?)\]", proto, re.S)
literal_events = re.findall(r'"([^"]+)"', m.group(1))

# ② 序列化器 + _node_event + router 里实际下发的 type 字面量
router = ROUTER.read_text(encoding="utf-8")
emitted = set(re.findall(r'"type":\s*"([a-z_]+)"', router)) | set(
    re.findall(r'type="([a-z_]+)"', router)
)
emitted |= set(re.findall(r'"type":\s*"([a-z_]+)"', proto)) | set(
    re.findall(r'type="([a-z_]+)"', proto)
)
events = sorted(set(literal_events) | emitted)


def class_fields(path: Path, cls: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            out = []
            for st in node.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    out.append(st.target.id)
            return out
    raise SystemExit(f"未找到类 {cls} @ {path}")


base = class_fields(BASE_HEALTH, "HealthResponse")
sub = class_fields(APP_HEALTH, "HealthResponse")
fields = base + [f for f in sub if f not in base]

print(f"StreamEventType Literal（{len(literal_events)}）: {literal_events}")
print(f"实现里实际下发的 type（{len(emitted)}）: {sorted(emitted)}")
print(f"==> 事件全集（{len(events)}）: {events}")
print()
print(f"共享基类字段（{len(base)}）: {base}")
print(f"agent_server 子类字段（{len(sub)}）: {sub}")
print(f"==> /health 字段全集（{len(fields)}）: {fields}")
```

---

## 2. IBM Plex：许可本体 + 六件字体实取体量

**命令**：

```bash
gh api -H "Accept: application/vnd.github.raw" repos/IBM/plex/contents/LICENSE.txt
gh api repos/IBM/plex/license | ConvertFrom-Json   # 取 .license.spdx_id
foreach ($p in 'plex-sans','plex-mono') { $r = gh api "repos/IBM/plex/contents/packages/$p/fonts/split/woff2" | ConvertFrom-Json; $r | Where-Object { $_.name -like '*Latin1*' } | ForEach-Object { "$p | $($_.name) | $($_.size)" } }
```

**许可读数**（raw 前四行，逐字）：

```
Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"

This Font Software is licensed under the SIL Open Font License, Version 1.1.

This license is copied below, and is also available with a FAQ at: http://scripts.sil.org/OFL
```

`spdx_id = OFL-1.1`，文件路径 `LICENSE.txt`。三条义务与落点在设计件 §1.4，本件只保证「许可本体确实直取到了，不是引二手」。

**体量读数**（`gh api contents` 的 `.size`，单位 = 字节；下面只列设计件要打包的六件，同目录另有 Bold/Italic/Light/Text/Thin 等 20+ 件未列）：

| 文件 | 字节 | ÷1024 |
|---|---|---|
| `IBMPlexSans-Regular-Latin1.woff2` | 20,984 | 20.49 KB |
| `IBMPlexSans-Medium-Latin1.woff2` | 21,960 | 21.45 KB |
| `IBMPlexSans-SemiBold-Latin1.woff2` | 22,260 | 21.74 KB |
| `IBMPlexMono-Regular-Latin1.woff2` | 17,544 | 17.13 KB |
| `IBMPlexMono-Medium-Latin1.woff2` | 17,868 | 17.45 KB |
| `IBMPlexMono-SemiBold-Latin1.woff2` | 17,872 | 17.46 KB |
| **合计** | **122,488** | **119.62 KB** |

**订正声明**（写在这里而不是悄悄改方案）：设计件 §1.4 原写「≈115KB」，那是**先把六件各自四舍五入到 0.1KB 再相加**（20.5+21.4+21.7+17.1+17.4+17.5 = 115.6）得来的，属于 §5-1 那条「分层的数必须逐层取」的变体失效——**合计必须从原始字节加**：`122,488 B`。设计件已就地订正为带字节准数的写法。数量级结论不变（< 125KB，够不上「大二进制资产」）。

**未覆盖**：`unicode-range` 的实际覆盖字符集未取（要解 woff2 的 cmap，得引第三方解包工具 ⇒ 与「依赖面克制」冲突）。PR-0 落地时若发现 Latin1 子集缺所需字形（例如框线字符 `▸ ⏸ ☰`），**这些符号一律走内联 SVG 而不是靠字体**（设计件 §1.4 已把图标定为 SVG，此格风险已被那条选择吸收）。

---

## 3. `@ibm/plex` npm 整包：否决依据

**命令**：

```bash
npm view @ibm/plex@6.4.1 license dist.unpackedSize dist.fileCount scripts.postinstall dependencies --json
```

**读数**：

```json
{
  "license": "OFL-1.1",
  "dist.unpackedSize": 186600620,
  "dist.fileCount": 10308,
  "scripts.postinstall": "ibmtelemetry --config=telemetry.yml",
  "dependencies": { "@ibm/telemetry-js": "^1.5.1" }
}
```

**口径**：版本号是本件现取的最新版 `6.4.1`（不是"某篇文章里说的版本"）。`unpackedSize` 是 npm registry 自己声明的解包后字节数。
**判定**：装一个**解包 186MB / 10,308 文件 / 带 postinstall 遥测**的包，只为拿 §2 那 122KB 的字形，且遥测与「离线自部署、不出域」直接冲突 ⇒ **否决**，走资产入库。设计件 §1.4 那条否决引的就是本表。

---

## 4. Radix Colors：令牌分层的实现形状（借结构，不搬色值）

**命令**：

```bash
$r = gh api repos/radix-ui/colors/contents/src | ConvertFrom-Json; $r | ForEach-Object { "$($_.name) | $($_.size) | $($_.sha.Substring(0,7))" }
gh api repos/radix-ui/colors/license | ConvertFrom-Json   # 取 .license.spdx_id / .name
```

**读数**：

```
blackA.ts | 993 | e8f333f
dark.ts | 58393 | 0005644
index.ts | 101 | 8dc6a55
light.ts | 58664 | ee3d9d9
whiteA.ts | 1065 | 4a87aa2
MIT | LICENSE | LICENSE
```

**取到的要素（只有形状）**：`light.ts` 与 `dark.ts` 是**同名两套**（同键、两套值，体量对等 58.6K/58.4K ⇒ 不是"一套主用一套补丁"），`blackA.ts`/`whiteA.ts` 把带 alpha 的变体**单列成独立令牌组**（体量 993/1065 B，说明它们是薄封装层不是第二套色板）。
**设计件对应落点**：§1.2 的「同值别名必须显式命名」+「组件里不写 `rgba()`，透明度底做成语义令牌」，§1.6 的「light 一套 + dark 两套声明」。
**明确没搬的**：Radix 的 12 档色阶数值一个都没进本设计（本件色相预算是 8 族 + 中性，与它的 scale 模型不同一套东西）。许可 `MIT` ⇒ 即便搬形状也只涉及署名义务，本件是**结构借鉴不是文本复制**，不触发。

---

## 5. 行为参照物 `console.html`：现状坐标复读（设计件里「继承」与「修正」两张表的事实基线）

**命令**（读工作树前 40 行并带行号）：

```bash
Get-Content applications/agent_server/static/console.html -TotalCount 40 | ForEach-Object -Begin {$i=0} -Process { $i++; "$i`t$_" }
```

**读数**（关键行逐字，行号 = 该文件在 rev `d140f91f` 的行）：

| 行 | 内容 | 设计件的用法 |
|---|---|---|
| `:8` | `:root { --line:#d8dee9; --dim:#6b7280; --ok:#0a7d33; --bad:#b00020; --warn:#8a6100; }` | `--dim → --text-2`、`--ok → --status-ok`、`--bad → --status-danger`、`--warn → --status-warn` **逐字继承** |
| `:10` | `body { … font:14px/1.6 system-ui,"Noto Sans CJK SC",sans-serif; color:#1f2937; background:#f6f7f9; }` | `--fs-body 14` / 行高 1.6 / `--bg-page #f6f7f9` / `--text-1 #1f2937` 四项继承（**中文栈也继承**，故 §1.4 那条「中文不打包」不是新决定，是沿用现状） |
| `:16` | `main { display:grid; grid-template-columns: 1.1fr 1.4fr 1fr; gap:12px; padding:12px; }` | 三栏比例逐字继承；`gap/padding 12px → --sp-3` |
| `:20` | `.ev { border-left:3px solid var(--line); … background:#fafbfc; font-size:12.5px; }` | **3px 左边框**这个图形通道继承；`#fafbfc → --bg-raised`；`12.5px` 归一到 `--fs-xs 12`（§1.5 那条「字阶 5 级封顶」的落点） |
| `:21`–`:26` | route `#2563eb` / evidence `#0a7d33` / replan `#8a6100` / memory `#7c3aed` / status `#0891b1` / error `var(--bad)` | **六类事件色值逐字继承**（设计件 §2.2 表的来源列就是这六行） |
| `:13`/`:14`/`:30` | `input… { border:1px solid var(--line); }`、`button { border:1px solid var(--line); }`、`#q { … border:1px solid var(--line); border-radius:8px; }` | ⚠ **此处不继承**：见下「修正一」 |
| `:32` | `.ref { … border:1px dashed var(--line); … color:#374151; }` | 依据列表的**虚线卡**形态继承；`#374151` 未进令牌表（该处文字按规则走 `--text-1`） |
| `:35`–`:38` | `.lamp .dot { … background:var(--dim); }` `.on → var(--ok)` `.off → var(--bad)` `.warn → var(--warn)` | ⚠ 灯卡四档里只继承 `on`/`warn`，`off` **不继承**：见下「修正二」 |

**修正一（控件边界，实测驱动）**：`--line #d8dee9` 被同时用作**分隔线**和**控件边框**。作边框时实测 **1.35:1**（§6 第 9 组），不达 WCAG SC 1.4.11 的 3:1 ⇒ `web/` 拆成 `--border-decor`（继承现值，只作分隔线）与 `--border-control`（新值 `#7d8794`，实测 3.64 / dark 3.52）。
**修正二（灯卡 `false` 档，语义驱动）**：参照物把 `off` 涂成 `--bad`（红），等于「未启用」与「坏了」同色。设计件把三档改为 `true → --status-ok 实心` / `false → --text-2 空心` / `null` 或 `DEGRADED → --status-warn`，理由是 AGENTS.md 那条「接线 ≠ 启用」——**红是失败色，未启用不是失败**。这是一处刻意偏离参照物，故写在本件里而不是让读者去设计件里猜。
**不改动声明**：`console.html` 本批**一行都不改**（它是 ADR-0010 选项 C 的证据基线，且路由集合被在册测试 `test_console_router.py:130-133` 锁着）。两条修正只作用于尚未创建的 `web/`。

**灯阵分组对派生集的覆盖核对**（§1 的 30 字段全集 vs 设计件 §2.3 的 5 组）：

| 组 | 数 | 与派生全集的差 |
|---|---|---|
| 平台基座 6 + 检索与缓存 8 + 执行平台 7 + 观测 4 + 数据面与工具 5 | **30** | **0**（无遗漏、无重复、无「界面上有但源里没有」的字段） |

核对方式是本件把两个集合并排写出来后人工逐条点的（不是"看起来都是 30"）。设计件 §2.3 明写「不写死 30」，真正的机器核对要到 PR-0 的 `check-tokens.mjs` 断言 6 —— **本件不能替它宣称已通过**。

---

## 6. 对比度实算：脚本全文 + 完整输出

**命令**：

```bash
uv run --no-sync python .tmp-scratch/ap-visual/wcag_contrast.py
```

**脚本位置**：`.tmp-scratch/ap-visual/wcag_contrast.py` —— **本机文件，不入库**；全文贴在下面以便任何机器照抄复跑（零第三方依赖，`python` 标准库即可）。

```python
"""WCAG 2.1 相对亮度对比度实算（零第三方依赖，纯标准库）。

判据来源：https://www.w3.org/TR/WCAG22/#contrast-minimum
  L = 0.2126 R + 0.7152 G + 0.0722 B，R/G/B 为线性化后的 0..1 分量
  线性化 c = c_srgb/255；c <= 0.03928 ? c/12.92 : ((c+0.055)/1.055) ** 2.4
  CR = (L_lighter + 0.05) / (L_darker + 0.05)

用法：uv run --no-sync python .tmp-scratch/ap-visual/wcag_contrast.py
"""

from itertools import chain


def lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def cr(fg: str, bg: str) -> float:
    a, b = rel_lum(fg), rel_lum(bg)
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


LIGHT_SURFACE = "#ffffff"
DARK_SURFACE = "#1c2128"
LIGHT_PAGE = "#f6f7f9"
DARK_PAGE = "#16191d"

# (标签, light fg, dark fg, 档位)  body=4.5 / graphic=3.0 / exempt=None（只出读数）
TEXT = [
    ("--text-1", "#1f2937", "#e6edf3", "body"),
    ("--text-2", "#6b7280", "#8b949e", "body"),
    ("--text-3", "#9199a3", "#6e7681", "exempt"),
]
BORDER = [
    ("--border-decor", "#d8dee9", "#30363d", "graphic"),
    ("--border-control", "#7d8794", "#6e7681", "graphic"),
]
ACCENT = [
    ("--cat-decision", "#2563eb", "#58a6ff"),
    ("--cat-progress", "#0891b1", "#3fc6d6"),
    ("--cat-source", "#0a7d33", "#3fb950"),
    ("--cat-memory", "#7c3aed", "#a371f7"),
    ("--cat-answer", "#0f766e", "#3fb9b0"),
    ("--cat-watch", "#8a6100", "#d29922"),
    ("--cat-failure", "#b00020", "#ff5c5c"),
    ("--cat-gate", "#475569", "#a8b1bc"),
]
TINT_LIGHT = ["#e8f0fe", "#e0f5f8", "#e6f4ea", "#f1ebfd", "#e5f2f1", "#fbf1de", "#fbe9ec", "#eef1f5"]
TINT_DARK = ["#1f2b3d", "#12303a", "#1c2e21", "#2a2140", "#15302f", "#332914", "#3a1c1f", "#262b32"]
THRESH = {"body": 4.5, "graphic": 3.0, "exempt": None}

# 两条“探针自身”正控（本仓 evidence-format.md §4：正控不成立时所有 PASS 读数无效）：
# ① 系数和必须为 1 —— 本轮实踩：把 0.0722 误写成 0.7216 后，全表读数被系统性抬高（17.64 等）；
# ② 已知答案对照：纯黑对纯白 = 21.0（WCAG 定义值）。任一条不成立即抛。
assert abs(0.2126 + 0.7152 + 0.0722 - 1.0) < 1e-9, "亮度系数和不为 1（探针自身错）"
assert abs(cr("#000000", "#ffffff") - 21.0) < 1e-6, "black/white != 21.0（探针自身错）"


def row(label: str, fg: str, bg: str, need) -> None:
    v = cr(fg, bg)
    verdict = "n/a" if need is None else ("PASS" if v >= need else "FAIL")
    need_txt = "  -  " if need is None else f"{need:4.1f}"
    print(f"{label:<40} {fg} on {bg}  CR={v:5.2f}  need>={need_txt}  {verdict}")


print("=== 0. 探针自身的已知答案对照 ===")
print(f"coef-sum={0.2126 + 0.7152 + 0.0722:.4f}  black/white CR={cr('#000000', '#ffffff'):.2f}  red/white CR={cr('#ff0000', '#ffffff'):.2f}")

print("\n=== 1. 正文层（对 --bg-surface） ===")
for label, lt, d, grade in TEXT:
    row(f"{label} [light]", lt, LIGHT_SURFACE, THRESH[grade])
    row(f"{label} [dark]", d, DARK_SURFACE, THRESH[grade])

print("\n=== 2. 边框层（对 --bg-surface） ===")
for label, lt, d, grade in BORDER:
    row(f"{label} [light]", lt, LIGHT_SURFACE, THRESH[grade])
    row(f"{label} [dark]", d, DARK_SURFACE, THRESH[grade])

print("\n=== 3. 分层：--bg-raised 对 --bg-page（不是判据，是「能否靠底色分层」的读数） ===")
row("bg-raised vs bg-page [light]", "#fafbfc", LIGHT_PAGE, 3.0)
row("bg-raised vs bg-page [dark]", "#22262d", DARK_PAGE, 3.0)

print("\n=== 4. accent 作图形通道（对 --bg-surface，档位 3.0） ===")
for label, lt, d in ACCENT:
    row(f"{label} [light]", lt, LIGHT_SURFACE, 3.0)
    row(f"{label} [dark]", d, DARK_SURFACE, 3.0)

print("\n=== 5. 同一批 accent 拿去当正文色（档位 4.5）——「色彩只作图形通道」这条规则的来处 ===")
for label, lt, d in ACCENT:
    row(f"{label} [light]", lt, LIGHT_SURFACE, 4.5)
    row(f"{label} [dark]", d, DARK_SURFACE, 4.5)

print("\n=== 6. primary 按钮前景 ===")
row("btn-fg light on --cat-decision", "#ffffff", "#2563eb", 4.5)
row("btn-fg dark on --cat-decision", "#0d1117", "#58a6ff", 4.5)

print("\n=== 7. tint 底上的文字：验证「tint 底上也只用 --text-1」 ===")
for tl, td, (label, _, _) in chain(zip(TINT_LIGHT, TINT_DARK, ACCENT)):
    row(f"--text-1 [light] on {label} tint", "#1f2937", tl, 4.5)
    row(f"--text-1 [dark] on {label} tint", "#e6edf3", td, 4.5)

print("\n=== 8. 反例：--text-2 落在 tint 上（「tint 底禁 text-2」的读数） ===")
for tl in TINT_LIGHT:
    row(f"--text-2 [light] on {tl}", "#6b7280", tl, 4.5)

print("\n=== 9. 参照物现状：console.html 的输入框边框（--line #d8dee9 勾控件） ===")
row("console.html input border [现状]", "#d8dee9", LIGHT_SURFACE, 3.0)
row("console.html route accent [现状]", "#2563eb", LIGHT_SURFACE, 3.0)
```

**读数（完整输出 92 行，逐字）**：

```
=== 0. 探针自身的已知答案对照 ===
coef-sum=1.0000  black/white CR=21.00  red/white CR=4.00

=== 1. 正文层（对 --bg-surface） ===
--text-1 [light]                         #1f2937 on #ffffff  CR=14.68  need>= 4.5  PASS
--text-1 [dark]                          #e6edf3 on #1c2128  CR=13.70  need>= 4.5  PASS
--text-2 [light]                         #6b7280 on #ffffff  CR= 4.83  need>= 4.5  PASS
--text-2 [dark]                          #8b949e on #1c2128  CR= 5.26  need>= 4.5  PASS
--text-3 [light]                         #9199a3 on #ffffff  CR= 2.88  need>=  -    n/a
--text-3 [dark]                          #6e7681 on #1c2128  CR= 3.52  need>=  -    n/a

=== 2. 边框层（对 --bg-surface） ===
--border-decor [light]                   #d8dee9 on #ffffff  CR= 1.35  need>= 3.0  FAIL
--border-decor [dark]                    #30363d on #1c2128  CR= 1.33  need>= 3.0  FAIL
--border-control [light]                 #7d8794 on #ffffff  CR= 3.64  need>= 3.0  PASS
--border-control [dark]                  #6e7681 on #1c2128  CR= 3.52  need>= 3.0  PASS

=== 3. 分层：--bg-raised 对 --bg-page（不是判据，是「能否靠底色分层」的读数） ===
bg-raised vs bg-page [light]             #fafbfc on #f6f7f9  CR= 1.03  need>= 3.0  FAIL
bg-raised vs bg-page [dark]              #22262d on #16191d  CR= 1.16  need>= 3.0  FAIL

=== 4. accent 作图形通道（对 --bg-surface，档位 3.0） ===
--cat-decision [light]                   #2563eb on #ffffff  CR= 5.17  need>= 3.0  PASS
--cat-decision [dark]                    #58a6ff on #1c2128  CR= 6.41  need>= 3.0  PASS
--cat-progress [light]                   #0891b1 on #ffffff  CR= 3.69  need>= 3.0  PASS
--cat-progress [dark]                    #3fc6d6 on #1c2128  CR= 7.91  need>= 3.0  PASS
--cat-source [light]                     #0a7d33 on #ffffff  CR= 5.26  need>= 3.0  PASS
--cat-source [dark]                      #3fb950 on #1c2128  CR= 6.37  need>= 3.0  PASS
--cat-memory [light]                     #7c3aed on #ffffff  CR= 5.70  need>= 3.0  PASS
--cat-memory [dark]                      #a371f7 on #1c2128  CR= 4.83  need>= 3.0  PASS
--cat-answer [light]                     #0f766e on #ffffff  CR= 5.47  need>= 3.0  PASS
--cat-answer [dark]                      #3fb9b0 on #1c2128  CR= 6.76  need>= 3.0  PASS
--cat-watch [light]                      #8a6100 on #ffffff  CR= 5.54  need>= 3.0  PASS
--cat-watch [dark]                       #d29922 on #1c2128  CR= 6.41  need>= 3.0  PASS
--cat-failure [light]                    #b00020 on #ffffff  CR= 7.33  need>= 3.0  PASS
--cat-failure [dark]                     #ff5c5c on #1c2128  CR= 5.35  need>= 3.0  PASS
--cat-gate [light]                       #475569 on #ffffff  CR= 7.58  need>= 3.0  PASS
--cat-gate [dark]                        #a8b1bc on #1c2128  CR= 7.46  need>= 3.0  PASS

=== 5. 同一批 accent 拿去当正文色（档位 4.5）——「色彩只作图形通道」这条规则的来处 ===
--cat-decision [light]                   #2563eb on #ffffff  CR= 5.17  need>= 4.5  PASS
--cat-decision [dark]                    #58a6ff on #1c2128  CR= 6.41  need>= 4.5  PASS
--cat-progress [light]                   #0891b1 on #ffffff  CR= 3.69  need>= 4.5  FAIL
--cat-progress [dark]                    #3fc6d6 on #1c2128  CR= 7.91  need>= 4.5  PASS
--cat-source [light]                     #0a7d33 on #ffffff  CR= 5.26  need>= 4.5  PASS
--cat-source [dark]                      #3fb950 on #1c2128  CR= 6.37  need>= 4.5  PASS
--cat-memory [light]                     #7c3aed on #ffffff  CR= 5.70  need>= 4.5  PASS
--cat-memory [dark]                      #a371f7 on #1c2128  CR= 4.83  need>= 4.5  PASS
--cat-answer [light]                     #0f766e on #ffffff  CR= 5.47  need>= 4.5  PASS
--cat-answer [dark]                      #3fb9b0 on #1c2128  CR= 6.76  need>= 4.5  PASS
--cat-watch [light]                      #8a6100 on #ffffff  CR= 5.54  need>= 4.5  PASS
--cat-watch [dark]                       #d29922 on #1c2128  CR= 6.41  need>= 4.5  PASS
--cat-failure [light]                    #b00020 on #ffffff  CR= 7.33  need>= 4.5  PASS
--cat-failure [dark]                     #ff5c5c on #1c2128  CR= 5.35  need>= 4.5  PASS
--cat-gate [light]                       #475569 on #ffffff  CR= 7.58  need>= 4.5  PASS
--cat-gate [dark]                        #a8b1bc on #1c2128  CR= 7.46  need>= 4.5  PASS

=== 6. primary 按钮前景 ===
btn-fg light on --cat-decision           #ffffff on #2563eb  CR= 5.17  need>= 4.5  PASS
btn-fg dark on --cat-decision            #0d1117 on #58a6ff  CR= 7.49  need>= 4.5  PASS

=== 7. tint 底上的文字：验证「tint 底上也只用 --text-1」 ===
--text-1 [light] on --cat-decision tint  #1f2937 on #e8f0fe  CR=12.81  need>= 4.5  PASS
--text-1 [dark] on --cat-decision tint   #e6edf3 on #1f2b3d  CR=12.08  need>= 4.5  PASS
--text-1 [light] on --cat-progress tint  #1f2937 on #e0f5f8  CR=12.99  need>= 4.5  PASS
--text-1 [dark] on --cat-progress tint   #e6edf3 on #12303a  CR=11.77  need>= 4.5  PASS
--text-1 [light] on --cat-source tint    #1f2937 on #e6f4ea  CR=12.93  need>= 4.5  PASS
--text-1 [dark] on --cat-source tint     #e6edf3 on #1c2e21  CR=12.16  need>= 4.5  PASS
--text-1 [light] on --cat-memory tint    #1f2937 on #f1ebfd  CR=12.61  need>= 4.5  PASS
--text-1 [dark] on --cat-memory tint     #e6edf3 on #2a2140  CR=12.79  need>= 4.5  PASS
--text-1 [light] on --cat-answer tint    #1f2937 on #e5f2f1  CR=12.79  need>= 4.5  PASS
--text-1 [dark] on --cat-answer tint     #e6edf3 on #15302f  CR=11.88  need>= 4.5  PASS
--text-1 [light] on --cat-watch tint     #1f2937 on #fbf1de  CR=13.10  need>= 4.5  PASS
--text-1 [dark] on --cat-watch tint      #e6edf3 on #332914  CR=12.11  need>= 4.5  PASS
--text-1 [light] on --cat-failure tint   #1f2937 on #fbe9ec  CR=12.56  need>= 4.5  PASS
--text-1 [dark] on --cat-failure tint    #e6edf3 on #3a1c1f  CR=13.01  need>= 4.5  PASS
--text-1 [light] on --cat-gate tint      #1f2937 on #eef1f5  CR=12.96  need>= 4.5  PASS
--text-1 [dark] on --cat-gate tint       #e6edf3 on #262b32  CR=12.06  need>= 4.5  PASS

=== 8. 反例：--text-2 落在 tint 上（「tint 底禁 text-2」的读数） ===
--text-2 [light] on #e8f0fe              #6b7280 on #e8f0fe  CR= 4.22  need>= 4.5  FAIL
--text-2 [light] on #e0f5f8              #6b7280 on #e0f5f8  CR= 4.28  need>= 4.5  FAIL
--text-2 [light] on #e6f4ea              #6b7280 on #e6f4ea  CR= 4.26  need>= 4.5  FAIL
--text-2 [light] on #f1ebfd              #6b7280 on #f1ebfd  CR= 4.15  need>= 4.5  FAIL
--text-2 [light] on #e5f2f1              #6b7280 on #e5f2f1  CR= 4.21  need>= 4.5  FAIL
--text-2 [light] on #fbf1de              #6b7280 on #fbf1de  CR= 4.31  need>= 4.5  FAIL
--text-2 [light] on #fbe9ec              #6b7280 on #fbe9ec  CR= 4.14  need>= 4.5  FAIL
--text-2 [light] on #eef1f5              #6b7280 on #eef1f5  CR= 4.27  need>= 4.5  FAIL

=== 9. 参照物现状：console.html 的输入框边框（--line #d8dee9 勾控件） ===
console.html input border [现状]         #d8dee9 on #ffffff  CR= 1.35  need>= 3.0  FAIL
console.html route accent [现状]         #2563eb on #ffffff  CR= 5.17  need>= 3.0  PASS
```

**口径**：`need>=4.5` 是 WCAG AA 正文档、`need>=3.0` 是图形件与控件边界档（SC 1.4.11）；`--text-3` 标 `n/a` 是**刻意不给判据**——它只允许出现在 disabled/placeholder，落在 AA 的「非活跃控件豁免」里，所以只出读数（2.88 / 3.52），出 PASS 会被误读成「可以拿它当正文色」。分母 = 17 组 × light/dark 两色 = 34 条 accent/边框/文字读数 + 16 条 tint 读数 + 8 条反例 = 全 92 行。
**FAIL 的 8 条不是失败，是本件的目的**：三条 `--border-decor`/`bg-raised` 类读数定下了「浅色分层靠 border 不靠底色」；八条 `--text-2 on tint` 定下了「tint 底禁 text-2」；一条 `--cat-progress [light]` 定下了「色彩只作图形通道」。

### 6.1 探针自身错的实踩（写下来，免得后人重犯）

首轮我把亮度系数写成 `0.2126 / 0.7152 / **0.7216**`（正确是 `0.0722`，抄漏一个小数点位移），跑出来的数**全都比正解高一大截**：`--text-1 [light]` 报 **17.64**（正解 14.68）、`--border-control [light]` 报 3.54、`--cat-progress [light]` 报 2.98——**而且 2.98 < 3.0 会让「图形通道达标」这条结论当场翻转**。是拿手算复核 `--text-1` 时发现对不上才暴露的，不是输出看起来不合理（表内所有数看着都"挺正常"）。

补救与固化：脚本里加了两条**探针自身**的正控（`coef-sum == 1` 与 `black/white == 21.0`，即 §6 输出的第 0 组），任一条不成立直接抛，不带病出表。这属 evidence-format.md §4 那条「正控本身必须能被判据命中」的同族应用——**区别**在于本轮命中的是探针自己而非被检对象：系数和为 1 这件事，错的样本（0.7216）会被断言拒绝，所以正控有效。订正后全表 92 行重跑，逐条与设计件 §1.3 的表核对一致。

**紧接上面的系数订正，还有一轮 ruff 可见的订正**：初版脚本用了 `l` 作变量名，`ruff check .tmp-scratch/ap-visual/` 报 **4 处 E741 Ambiguous variable name**（`ruff check .` 不报，因为 `.tmp-scratch/` 被 ignore 规则排除在外 ⇒ **门禁的默认覆盖面不能当成“全仓都干净”**）。本件上面贴的是订正后的版本（`l → lt`）。重跑后的输出与订正前**逐字节相同**：`Compare-Object` 行数差 = **0**，两侧 `sha256` 都是 `C9DB19DF48251E177AC3F510C02730888A7E8463B8BC36FFE738F43CB7A77E2C`——**纯改名不动读数**这件事得这么写，不能只说“不影响”。本轮 `uv run --with ruff ruff check .tmp-scratch/ap-visual/` rc=**0**（两个脚本都干净）。

---

## 7. 第 5 个参照取证：Jaeger UI 与 Langfuse trace 视图

**状态**：✅ **已取证**（本窗口 2026-10-30 `gh api` 现取，公网）。**订正声明**：本节上一版写的是「未取证」，且 §0 第 9 行、§8 未覆盖表、设计件 §4 第 5 行、工单件 §13.4 末行都标的是未取证——那一版把「本批不阻塞」误写成「本批未做」；用户 2026-10-30「继续」指令下本格已补跑。**结论：未推翻任何设计值，但补强了 §1.2 / §1.3 / §2.1 / §2.2 / §2.3 五条。** 上面那四处「未取证」标记已随本批同步翻转（§0 第 9 行、§8 末行、设计件 §0.2 第 3 条与 §4 第 5 行、工单件 §13.4 末行、顶层 docs 索引取证件那一行）；**本节保留这段订正声明的目的，就是让下一次读到的人知道这个标记曾经错在哪**（把「本批不阻塞」当成「本批未做」），而不是留着当现状读。

**命令（已执行，PowerShell 原生；`--jq`/`--timeout` 会被宿主拆参或非法，故用 `ConvertFrom-Json` 本地筛）**：

```powershell
# ① Jaeger：先列全树定位样式件（不猜路径）
(gh api "repos/jaegertracing/jaeger-ui/git/trees/HEAD?recursive=1" | ConvertFrom-Json).tree | Where-Object { $_.path -match '\.css$' } | ForEach-Object { "{0} ({1} B)" -f $_.path, $_.size }
# ② 直取两个关键件原文
gh api -H "Accept: application/vnd.github.raw" "repos/jaegertracing/jaeger-ui/contents/packages/jaeger-ui/src/components/common/vars.css"
gh api -H "Accept: application/vnd.github.raw" "repos/jaegertracing/jaeger-ui/contents/packages/jaeger-ui/src/components/TracePage/TraceTimelineViewer/SpanTreeOffset.css"
# ③ Langfuse：license + 全树 + 依赖面 + 全局样式件
(gh api repos/langfuse/langfuse | ConvertFrom-Json).license
(gh api "repos/langfuse/langfuse/git/trees/HEAD?recursive=1" | ConvertFrom-Json).tree | Where-Object { $_.path -match '^web/src/.*(race|pan|Timeline).*\.tsx$' -and $_.path -notmatch 'test|stories' }
gh api -H "Accept: application/vnd.github.raw" "repos/langfuse/langfuse/contents/web/package.json"
gh api -H "Accept: application/vnd.github.raw" "repos/langfuse/langfuse/contents/web/src/styles/globals.css"
```

### 7.1 Jaeger UI 读数（Apache-2.0，文件头 `SPDX-License-Identifier: Apache-2.0` 两处实取）

- 全树 **1092 条目**，`.css` **117 件** ⇒ 形态 = **每组件一 CSS 文件**（与本件「组件不自行引样式片段」相反，但它是库级项目，不在本件射程）。
- **`common/vars.css` = 10,575 B 的集中令牌面**，分组注释直接写着 `SURFACE / TEXT / BORDER / INTERACTIVE / FEEDBACK / SHADOW TOKENS`，令牌名如 `--surface-primary` `--text-primary` `--border-default` `--interactive-primary` `--feedback-error`——**这正是设计件 §1.2 的 L1 语义层的业界形状**（但它把 L0 primitive 外包给了 antd：值全是 `var(--ant-color-*)` 别名 ⇒ 印证 §1.2 的 **L2 别名「同值必须显式命名」**）。
- **hex 被关在令牌文件里**：`vars.css` 内可见 `--action-apply-background: #4c21ce`、`--interactive-primary-rgb: 17, 147, 154`，组件件里不出现裸 hex ⇒ **独立佐证 §6 断言 1（tokens.css 为唯一色值源）不是本件自创的严律**。
- **tint / muted 用 `color-mix()` 不用 inline rgba**：`--text-muted: color-mix(in srgb, var(--ant-color-text) 50%, transparent)`；连接线与填色用命名 alpha 令牌 `--tree-chrome-strength` / `--tree-chrome-fill` ⇒ **§1.2 从 Radix `blackA/whiteA` 借的那条「alpha 做成独立令牌」形状，此处得到第二个业界佐证。**
- **状态色只作图形通道——被 Jaeger 自己的命名拆出来**：`--feedback-error`（填/图形）与 `--feedback-error-text`（色上的文字）**是两个不同令牌**，注释原文：“Use `--feedback-error-text` for text/border on transparent backgrounds; adapts to dark theme.” ⇒ **直接互证 §1.3 那条「色彩只作图形通道、文字另取 `--text-1`」不是审美选择而是可达性铁律。**
- **阴影三档**（`--shadow-sm/md/lg` + focus/sidepanel 两枚专用）——本件定的是 ≤ 2 档（§1.3），**这是刻意更严的预算，不被推翻**（Jaeger 是富交互图平台，本件是最小核心）。
- **`--span-color-1 … -19+` = IBM Carbon 分类色板**（注释外链 carbondesignsystem，且逐档标 `Cyan 60 / Orange 60 …`）⇒ 这是**为「任意多个服务/操作」做数据可视化分类**的开放色板，与本件「固定 8 族事件语义」是两种用途；**借它证明分类色板与语义色板必须分家，不借它的 19 色。**
- **span 父子层级 = 三通道并用**（`SpanTreeOffset.css` 全文实取）：① 缩进（`--indentGuide` 宽 `calc(0.5rem + 20px)`）；② **竖连接线** `::after` 1px（`left: calc(0.25rem + 9.5px)`，`background: color-mix(… currentColor var(--tree-chrome-strength), transparent)`）+ **横连接线** 1px；③ **形状**：parent = 空心 box（20×20，`border: 1px solid`，`border-radius: 3px`），leaf = 实心 dot（8×8，`border-radius: 50%`）。注释还写「折叠只改 fill，不改 border strength，因为折叠不改变该 span 属于哪个服务」。

### 7.2 Langfuse 读数（`license: NOASSERTION / Other` = 混合许可，非纯 MIT）

- 全树 **9620 条目**；`web/package.json` 依赖面 = **Next.js（SSR）+ Tailwind v4（`@theme`）+ 20 个 `@radix-ui/react-*` 原语 + class-variance-authority + tailwind-merge**；`globals.css` = **44,144 B** 单文件。⇒ 这是本设计**刻意不走**的主流路径（§5 已定不引 CSS 框架 / 不装组件库 / 不引 SSR）。**它的价值恰在作反面参照，坐实「不引框架」是有意识取舍而非遗漏。**
- 但它仍**收紧色相预算**：`@theme` 里 `--color-lime-*/cyan-*/sky-*/fuchsia-*/rose-*/neutral-*/stone-*/slate-*/zinc-*/indigo-*: initial`（成批清空 Tailwind 默认色板），且沿用 shadcn 的 `hsl(var(--x))` 令牌间接层 ⇒ **「令牌预算要收窄」这条纪律在 Tailwind 阵营里同样成立，与 §1.3 的 ≤8 色相预算互证。**
- **trace/session 时间线 = 折叠行 + 深层嵌套组件**（`…/SessionTranscriptContent/…/SessionTimelineCollapsibleRow.tsx` 等，实取路径），**不用连接线画层级** ⇒ 判据 1 的另一种答案：层级靠「可折叠 + 逐层组件」读，不靠连接线。
- 一处 SSR 专属坑（`globals.css` 注释原文）：“next/font CSS is silently dropped in `_document`” ⇒ 反证「不引 SSR」这条约束替本件**省掉了一整类此类构建期陷阱**。

### 7.3 三判据的回答

1. **窄栏里 span 层级靠什么读出**：Jaeger = 缩进 + 竖/横连接线 + 形状（box/dot）三通道；Langfuse = 折叠行 + 嵌套。**对本设计的定论**：本件 §2.2 的时间线是**固定 12 类扁平事件**（不是任意深度的 span 树），故「缩进 + 类型徽标文本（mono 常显）+ 3px 左边框」三通道已足，**不引入 `::after` 连接线**（那属 span 树的需求，硬搬会超出 §13.1 第 2 格的射程）；而 §2.1 在 768–1279 用原生 `<details>` 折叠、<768 折叠为计数徽标，与 Langfuse 的 CollapsibleRow 同理 ⇒ **该取舍得到参照佐证，非凭空**。
2. **状态色是否只作图形通道**：Jaeger 把 `--feedback-error` 与 `--feedback-error-text` 拆成两令牌 ⇒ **互证本件 §1.3**，无反证。
3. **色值/令牌是否可借**：**借形状与纪律，不搬色值**——Jaeger（Apache-2.0）借的是「语义令牌分组 + hex 关在令牌文件 + alpha 做成命名令牌 + 状态色拆文字/图形两令牌 + 层级用形状（空心/实心）区分」这些实现形状；色值**一个不搬**（它的 `--span-color-*` 是 Carbon 数据可视化分类板，用途不同）。Langfuse 代码**不可借**（NOASSERTION 混合许可），只作反面参照。**预期结论成立**（上一版预告的「不可借」得到证实），但**修正一处**：上一版本节写“Langfuse 是 MIT”，实取为 **NOASSERTION/Other**。

**强度分档**：本节 = **已验证**档（本窗口 `gh api` 现取，命令可复跑）；但“借什么”属设计判断，仍归设计件（本件只放读数）。


---

## 8. 未覆盖清单（字段 4：没跑的部分与原因）

| 没跑的 | 原因 | 什么时候必须跑 |
|---|---|---|
| V1–V7 任何一条 | 无 `web/` 可跑（本批零产品代码） | PR-0/PR-2/PR-4 交付批，逐条实拍 |
| `check-tokens.mjs` 六条断言 + 反证表 | 脚本与样式文件都还不存在 | PR-0，且反证表六格须**逐格实取**（设计件 §6 只定了形状） |
| Latin1 子集的 `unicode-range` 覆盖字符集 | 需解 woff2 cmap，与「依赖面克制」冲突 | 不做；符号走内联 SVG（§2「未覆盖」） |
| 真实浏览器渲染下的对比度（字体抗锯齿、半透明叠加） | 无 UI 可渲染；本件是**公式层**读数 | V5：实拍图上按像素取一次，与公式值互核 |
| `console.html` 的两处修正落地 | 该页本批不改（在册测试锁 + ADR-0010 证据基线） | 若有人把它列为对外界面，或 roadmap #18 关闭批允许动（设计件 §9 排除项 2 的复审条件） |
| Jaeger / Langfuse 取证 | ✅ 本窗口已补跑（见 §7）；上一版列在未覆盖表是错的 | —（已取） |
| Radix / VitePress 色值与排版取证 | ✅ 同日第四批已跑（见 §11.2 / §11.3） | —（已取） |
| **CJK 回落脚本下的实际行盒度量**（行高 1.6→1.7 的观感） | §1.4 已定**中文不打包**，而混排行的行盒由回落脚本（Noto Sans CJK SC / 雅黑）决定，与 Plex 不同；本批只算过 Latin1 形状 | V1 截图批：中文密集页实拍一次，与 1.7 的设计值互核 |
| perceptual diff / 实拍“是否真变好看” | 无 `web/` 可渲染；§11.5 那五条纪律的强度来自**两个独立来源同形**，不来自读数 | V1/V5 实拍批；拿不到实拍就得按「主张」引用，不得写成已证 |

**强度分档声明（字段 3/5 收口）**：本件 §1–§7 的外部与公式读数是**已验证**档（五字段齐、命令当场可复跑；§1–§6 绑定 rev `d140f91f`，§7 绑定本窗口的 `gh api` 公网现取）；**上表那一格未跑的（V1–V7 / `check-tokens.mjs` / 浏览器实渲染对比度 / console 修正落地）是待环境档**，**不得**在任何下游文档里被写成「视觉验收已过」——取证与实算是证据，V 系列是拿 `web/` 实拍才能结的判据。

---

## 9. 与设计件的引用关系（避免"两处漂"）

| 本件小节 | 设计件消费处 |
|---|---|
| §1 派生集 | §2.2 图例 12 行、§2.3 灯阵 5 组、§6 断言 6 |
| §2 字体许可与体量 | §1.4 三条义务 + 打包形态（**体量以本件 122,488 B 为准**） |
| §3 npm 元数据 | §1.4 那条「否决」 |
| §4 Radix 结构 | §1.2 三层令牌、§1.6 双 dark 声明 |
| §5 console.html 现状 | §1.3 继承的六个色值、§2.1 三栏比例、§2.3 灯卡；**两条修正**（控件边界、`false` 档） |
| §6 对比度全表 | §1.3 色值表的每一行、§1.3 那条「色彩只作图形通道」规则、§3 可达性线 |
| §7 Jaeger/Langfuse 已取证 | §4 第 5 行（已从未取证改已取证）、§2.1/§2.2 的折叠与层级通道取舍 |
| §11.2 Radix 四张 12 档表 + 三条形状读数 | §1.2 L0 「档号↔用途」映射一句（**色值未进设计件**） |
| §11.3 VitePress 令牌/排版实取 | §1.1 `base.css` 职责边界（佐证）、§1.5 新增「字距」行与双层阴影形状 |
| §11.4.1 成族性 16 枚读数 | §1.3 表后那条新增注记（「色板已在蓝相带，不得再提加微染」） |
| §11.4.2 六条候选对比度（含一条 FAIL） | §1.3 色值表**一个 hex 未改**的事实依据；§4 「不借色值」的第二次实证 |
| §11.4.3 底色差 1.03 / 1.16 | §1.3 `--bg-raised` 行 + §1.5 阴影行（分层依据升为两主题通用） |
| §11.5 五条纪律 + 四条借不到 | §9 默认值新增 ⑥（排版三值）、§4 参照列新增 VitePress 第 6 行与 #3 出处补充、§1.5 新增字距/行高两行、§6 断言 4 加两子句 |

引用方向是**单向**的：设计件引本件（读数与出处）；本件不复述设计取舍（免得两份文件各写一遍、改一处漏一处）。

---

## 10. 本批自查门禁的实测读数（四道 + 一道覆盖面告警）

环境：分支 `feat/nl2sql-ttl-and-006-slim`，`git rev-parse --short HEAD` = **`d140f91f`**（本批**未提交** ⇒ 一切“自证零改动”不能用 `d140f91f..HEAD` 那个形态，两端同一个 commit，空得毫无意义）。本机 = PowerShell（下面命令逐字拷自实跑，`&&` 不可用故用 `;`）。

| # | 命令 | 读数 | 判读 |
|---|---|---|---|
| 1 | `git diff --name-only d140f91f -- applications/ packages/ scripts/ Makefile Dockerfile .dockerignore .github/workflows/ ARCHITECTURE.md CHANGELOG.md AGENTS.md` | 输出**空**；同行 `(… \| Measure-Object).Count` = **0** | ✅ 后端目录/构建面/顶层三份真相件均未动 ⇒ V7 那条「后端 diff 为空」的反证形状成立 |
| 2 | `git status --short` | 四行：` M docs/README.md`、` M docs/plans/plan-web-frontend-minimal-core-2026-10-29.md`、`?? docs/operations/evidence/2026-10-30-web-visual-references/`、`?? docs/plans/plan-web-visual-design-2026-10-30.md` | ✅ 改动集 = 计划定的四个文件动作，全在 `docs/` |
| 3 | `git status --short --untracked-files=all \| Where-Object { $_ -notmatch 'docs/' }` | **空** | ✅ 展开到单文件粒度也没有 `docs/` 外的新增 |
| 4 | `Test-Path web`；`(git status --short --untracked-files=all \| Select-String -Pattern '\.(css\|vue\|ts\|mjs\|woff2)$' \| Measure-Object).Count` | **False** / **0** | ✅ 未建 `web/`、未写一行样式或产品代码；未跑 `pnpm install` |
| 5 | `uv run --no-sync python scripts/check_doc_sync.py` | `✅ 文档同步校验通过（0 警告）`，rc=**0** | ⚠ 绿，但**不构成引用边证明**，见下面「覆盖面」 |
| 6 | `uv run --with ruff ruff check .` | `All checks passed!`，rc=**0** | ✅ 仓内 Python 干净（本批未动 `.py`） |

### 覆盖面：`check_doc_sync.py` 根本不扫 `docs/` 下的路径引用

不是猜的，是按源代码读出来的：`DOC_FILE_REF_DOCS = ("AGENTS.md", "ARCHITECTURE.md", "README.md")`（`scripts/check_doc_sync.py:41`）⇒ 只有这三份**顶层**文档里的反引号路径会被校存在性；存在性基准是 `git ls-files -z`（`:98-116`，**不带 `--others`**），`:145-154` 那段写明本机 FS 只用于**区分措辞**不参与判定。两条推论：

1. **`docs/README.md`（§3.9 那两行）与 `docs/plans/*.md`（设计件/取证件/工单件）里的路径引用不在这个门禁面上** ⇒ rc=0 不等于「本批新加的互指路径能解析」。
2. 未提交的文件它看不见 ⇒ 「§8 第 5 条：引用边必须同批入库」只能靠**人工保证同批 `git add`**，门禁不兑。

于是做了一次就地自查（零依赖，PowerShell 原生；抽四份文档里所有形如 `` `docs/…` `` 的反引号路径，逐条 `Test-Path` + 查是否在 `git ls-files`）：

```powershell
$files = @('docs/README.md','docs/plans/plan-web-visual-design-2026-10-30.md',
  'docs/operations/evidence/2026-10-30-web-visual-references/readings.md',
  'docs/plans/plan-web-frontend-minimal-core-2026-10-29.md')
$tracked = git ls-files
foreach ($f in $files) {
  ([regex]::Matches((Get-Content $f -Raw), '(?m)`([^`\r\n]+)`') | ForEach-Object { $_.Groups[1].Value }) |
    Where-Object { $_ -match '^docs/[A-Za-z0-9._/\-]+$' -and $_ -notmatch '\*$' } | Sort-Object -Unique |
    ForEach-Object { [pscustomobject]@{ Ref=$_; Exists=(Test-Path $_); Tracked=($tracked -contains $_) } }
}
```

**读数**（⚠ 本段全部数字是**第二批当时的快照**，第三批复跑值见 §10.1）：`total=136`（四份文档里的 `docs/` 路径引用总次数）/ `unique=68` / **不可解析 4 条**，且**本批新增的引用一条都不在其中**：视觉件文件名在取证件命中 2 次（第三批已变，见 §10.1）、在工单件命中 3 次，全部 Exists=True；取证件目录名那一条也 Exists=True（两条 **Tracked=False 正是“本批未提交”这件事本身**，不是断链，`git add` 后自愈）。四条不可解析的全是本批**没动过**的历史账面，即下面那两条。

⚠ **这组数被本件自己推着走**：本节下面那段把视觉件文件名又写了两遍（脚本里一遍、`.mX` 夹具里一遍），所以“引用边计数”不能当常量读，也不能跨批复用——**谁改了这四份文件里任一处文件名，谁就得重跑 §10.1 那两条计数**。第三批复跑实测已把它从 136/68 推到 §10.1 的值。

⚠ **非空转反证（已实跑）**：把上面那段里的正则命中项取最后一个字符改成 `X` 再跑一次 → `docs/plans/plan-web-visual-design-2026-10-30.mX` 报 **Exists=False**（真路径报 True）⇒ 这段自查能命中坏引用，不是恒绿。同型证据：上面那四条“不可解析”的存在本身就是它在工作。

### 自查顺带查出的两处既有悬空引用（**本批不修**，只登记）

两者都在 `docs/README.md`，都是本批**没动过**的行（历史账面），且修它超出 §0 射程（那四个动作之外的第五个文件改动）：

1. **ADR 无扩展名短写**（共 3 条）：`docs/adr/0003`、`docs/adr/0012`、`docs/adr/0013` ⇒ 真名是 `docs/adr/0003-dual-db-driver.md` 这类带后缀的全名（`git ls-files docs/adr` 实取）。不算断链，但任何按「路径存在性」扫的脚本会误报（包括上面那段自查）。
2. `docs/plans/README.md` **不存在**：实取 `Get-ChildItem docs/plans -Filter 'README*' -Recurse` 只有 `docs/plans/archive/README.md`，而 `docs/README.md` 里有一句（写于 2026-10-16）把它说成「新增的 1 篇」⇒ 账面未跟。按台账 §4 **C8** 的纪律，定位这句靠**内容**不靠行号：`git grep -n --untracked -F 'docs/plans/README.md' -- docs`（本轮命中的是 `docs/README.md:212`，**行号只作 `d140f91f` 快照用**，下一批往该文件开头加行就会漂）。

> 这两条的处置 = **待你拍板**：要不要另开一个账面小批修「新增的 1 篇是 `docs/plans/README.md`」那句（它同时影响 §3 那串分母计数口径的可复核性）。本批不自行放宽射程。

---

### 10.1 同日第三批（补 Jaeger/Langfuse 取证）的复跑读数

环境不变：HEAD 仍 = **`d140f91f`**（本批仍**未提交**）、分支 `feat/nl2sql-ttl-and-006-slim`。第三批只动 `docs/` 四份文件的账面表述（新写了上面 §7 那一节）+ 本节，**零产品代码**，所以六条门禁逐条复跑了一遍：

| # | 命令 | 复跑读数 | 与第二批比对 |
|---|---|---|---|
| 1 | `git diff --name-only d140f91f -- applications packages scripts tests eval deploy Makefile pyproject.toml` | 行数 **0** | 不变 ✅ |
| 2 | `git status --short --untracked-files=all \| Where-Object { $_ -notmatch 'docs/' }` | **空** | 不变 ✅ |
| 3 | `Test-Path web` | **False** | 不变 ✅ |
| 4 | `uv run python scripts/check_doc_sync.py` | `✅ 文档同步校验通过（0 警告）`，rc=**0** | 不变（⚠ 覆盖面告警仍成立，它不扫 `docs/`） |
| 5 | `uv run --with ruff ruff check .` | `All checks passed!`，rc=**0** | 不变 |
| 6 | 就地引用边自查（上面那段脚本，原样重跑） | `total=**139**` / `unique=**69**` / `unresolved_unique=**5**` | 三值均涨；**新增 0 条真断链** |

第 6 条那 `5` 里含上面那条变异夹具（故意把末字符改成 `X` 的那个），剔掉它 = **既有悬空仍为 4 条**，与第二批逐字同一集（ADR 短写 3 条 + 那篇不存在的 plans 索引）⇒ **本批没引入新的不可解析引用**，这是本节要结的那一条判据。

提及数同步复跑（`(git grep -o --untracked -- "<令牌>" | Measure-Object).Count`，不带 `.md` 后缀）：视觉件 **8**（取证件 4 / 工单件 3 / 顶层 docs 索引 1）、取证件目录名 **9**、工单件 **11**。⚠ 这个 8 与第二批写的 8 **数值相同但不是同一份账面**：第二批是 8，本批写 §7 订正声明时先推到 9，然后又把 §10 那段的反引号文件名改成了中文指代（「视觉件文件名」）⇒ 回到 8。**正是这种“改一处文字就改一个计数”的属型，决定了这组数只能当“此刻工作树”的读数，不得抄进任何下游文档当常量**（顶层 docs 索引 §3.9 那张表的“提及”列已按本批复跑值对齐）。

### 10.2 同日第四批（C 路取证 + 两条证伪 + 四处账面随动）的复跑读数

环境不变：HEAD 仍 = **`d140f91f`**（本批仍**未提交**）、分支 `feat/nl2sql-ttl-and-006-slim`。第四批的改动面 = 本件新增 §11 全节 + 视觉件六格（§1.2/§1.3/§1.4/§1.5/§4/§6/§8/§9 内的若干处）+ 工单件三处（§7 / §9.3 / §13.4）+ 顶层 docs 索引 §3.9 三行，**零产品代码**（未建 `web/`、未写一行 CSS/TS/Vue、未跑 `pnpm install`、未 `git add`）。

⚠ **第 8 道是本批新加的**：上一批实踩过「编辑时删掉某行行首竖线、把一张表塌成散文」这一型，而另七道没有一道拦得住它（`check_doc_sync` 只看路径存在性，`ruff` 不看 md）。判据 = 扫「以竖线开头、但行尾不是竖线」的行。它与另七道一样只证**形状**（表没塌），不证表内容对。

| # | 命令 | 第四批复跑读数 | 与第三批（§10.1）比对 |
|---|---|---|---|
| 1 | `git diff --name-only d140f91f -- applications packages scripts tests eval deploy Makefile pyproject.toml` | 行数 **0** | 不变 ✅ |
| 2 | `git status --short --untracked-files=all \| Where-Object { $_ -notmatch 'docs/' }` | **空** | 不变 ✅ |
| 3 | `Test-Path web` | **False** | 不变 ✅ |
| 4 | `uv run --no-sync python scripts/check_doc_sync.py` | `✅ 文档同步校验通过（0 警告）`，rc=**0** | 不变（⚠ 本节上面那条覆盖面告警仍成立：它不扫 `docs/` 下的引用边） |
| 5 | `uv run --with ruff ruff check .` | `All checks passed!`，rc=**0** | 不变（本批仍未动 `.py`。⚠ 两个取证脚本住在一处 gitignored 目录里，`ruff check .` **根本不扫它们** ⇒ 这一道 rc=0 不等于“取证脚本也干净”，脚本自己的那一轮在 §6.1（含 E741 实踩）与 §11.1 命令块，都是单独跑的） |
| 6 | 就地引用边自查（本节上面那段脚本，第三轮原样重跑） | `total=**139**` / `unique=**69**` / `unresolved_unique=**5**` | **三值逐字相同** ⇒ 本批新增 0 条引用边、0 条断链 |
| 7 | 提及数（令牌**不带** `.md`，`git grep -o --untracked`） | 视觉件 **8** / 取证件目录名 **9** / 工单件 **11** | 三值不变 |
| 8 | 表格完整性扫描（行首竖线而行尾非竖线） | 四份文件各 **0** 命中 | 无对照（该道第三批不存在） |

**第 6 条为什么这次能当判据用**：本批往那四份文件里加了三张 hex 数值表、十余个 §11.x 指代、两枚新令牌族名，却**一个「反引号包住的 docs 斜杠路径」都没新增** —— 这是下笔时刻意的（复跑台账里指代那三份文件一律用中文「视觉件 / 取证件 / 工单件」，不重写文件名）。所以 139/69/5 不动是**做出来的**，不是巧合。这正是本节上面那条「计数被本件自己推着走」的可控形态：**要让引用边计数不动，就别在记读数的段落里重复文件名或新写路径**。

**第 7 条怎么说才不 over-claim**：三个数与第三批相同，其中视觉件那 8 次的**分文件构成**已复量、且与 §10.1 记的分布逐文件相同（本件 4 / 工单件 3 / 顶层索引 1）⇒ 这一格是「数值相同、构成也相同」，与 §10.1 那次的「数值相同但构成变了」正好对照。另两个数（9、11）第三批**只记了总数、没记分布**，所以本批**无权**声称它们的构成未变 —— 从本批起把分布记死，作为下一批的对照基线：

- 取证件目录名 **9** = 本件自身 2 / 工单件 3 / 视觉件 2 / 顶层索引 2。
- 工单件 **11** = 本件 2 / 视觉件 1 / 工单件自身 1 / 顶层索引 1 / ADR-0010 1 / revert-checkpoint 方案件 2 / 另三份取证目录各 1（revert-checkpoint-probe、roadmap-18-console、frontend-preflight）。

⚠ 口径分叉要在档：`-o` 数的是**出现次数**，`-c` 数的是**命中行数**。本例每个命中行只出现一次令牌，两口径同值（上面那个分布是用 `-c` 取的）；换批若出现同一行写两遍文件名，两口径就会分叉，届时必须写明用的是哪个数，否则「8 次」这种说法无法复核。

**闭合判定**：八道全绿 + 两条证伪已落进视觉件正文（§1.3 那两条 ⚠ 注记）+ 落点逐行表在本件 §11.6 ⇒ 第四批的账面自证闭合。**这批没有冒充任何未取的读数**：V1–V7 仍**一条未取**、视觉件仍**待用户点头**、PR-0 开工授权仍**未给**。

---

## 11. C 路取证（同日第四批）：Radix 中性族数值表 + VitePress 令牌/排版件 + 中性色实算

**触发**：用户问「新前端要好看一些怎么弄、能否从 GitHub 找借鉴对象」，并对**「不引任何 CSS 框架」这条用户给定默认值**（设计件头部「触发」行的 ①；⚠ **不是**设计件 §9 那张默认值表里的 ① —— 那个是「主题跟随系统」，两个编号重名易混）的代价给了取向：「按你推荐的做」= **走 C 路（不引任何库，只借开源的数值表与纪律）**。本批零产品代码。

**环境**：HEAD 仍 = **`d140f91f`**（未提交）。外部读数 = `gh api` 公网现取；算式读数 = 本机 `uv run --no-sync python`。

### 11.1 命令（已执行）

```powershell
# —— 外部取证（gh api，PowerShell 原生筛）——
(gh api repos/radix-ui/colors | ConvertFrom-Json)                       # 许可/体量
(gh api "repos/radix-ui/colors/git/trees/HEAD?recursive=1" | ConvertFrom-Json).tree   # 全仓 22 条目
gh api -H "Accept: application/vnd.github.raw" "repos/radix-ui/colors/contents/src/light.ts" | Select-String -Pattern '^\s*slate(1|2|…|12):\s'
#   （gray / sage / mauve 同式；dark.ts 同式取 slate / gray）
gh api -H "Accept: application/vnd.github.raw" "repos/vuejs/vitepress/contents/src/client/theme-default/styles/vars.css"
gh api -H "Accept: application/vnd.github.raw" "repos/vuejs/vitepress/contents/src/client/theme-default/styles/components/vp-doc.css"
# —— 本地实算 ——
cd .tmp-scratch/ap-visual; uv run --no-sync python neutral_family.py      # rc=0；4/4 探针全杀
uv run --with ruff ruff check .tmp-scratch/ap-visual/                     # rc=0（在册默认覆盖面盲区，同 §6.1）
```

⚠ **两个必须随读数一起说的条件**：① `neutral_family.py` 与 `wcag_contrast.py` 均在 **gitignored 的临时目录**（不入库，台账 D26 那条）⇒ 判据本体已写在下面 §11.4，拿不到脚本也能复算；② `wcag_contrast.py` **没有 `__main__` 守卫**（实取：它的 `print` 写在模块级，行 74/77…），所以 `neutral_family.py` 里那一句 `from wcag_contrast import cr, rel_lum` **会连带把 §6 那张旧表重新打印一遍**：本批实测输出 = **147 行**（按 `@(… | ForEach-Object { "$_" })` 取数组长度；同一个输出用 `Out-String -split` 量得 **148**，差的那 1 行是尾部换行产生的空元 ⇒ 两个都是对同一输出的量法，引用时请连带说口径）。分段行号已定位：`=== light：现有中性令牌 ===` 在 **第 95 行**（0-based 下标 94）⇒ **旧表占前 94 行**（第 94 行是分隔空行），**本批新读数 = 第 95–147 行共 53 行**。⚠ **与 §6 那句「92 行」的口径差**：§6 的 92 是**单独跑 `wcag_contrast.py`** 时的行数，而这里的 94 多了尾部一个空行与一句 `[probe]` 自证行 ⇒ **两个数都对，但不得互替**（引用时请说“§6 那张表”，不要拿行数当指纹）。（本批输出全文 sha256 = `EF4FD8669F0C5AE0DE08423A1CAC899E41D077E4D11E1C52CB82B18B0187BAE3`，本窗内两次独立复跑得到同一值 ⇒ 逐字可比，不依赖终端宽度〔不同于 `gh pr diff` 那类坑〕。）

### 11.2 Radix Colors（**MIT**，stars **1,725**，全仓仅 **22 条目**）

令牌本体文件体量：`src/light.ts` **58,664 B** / `src/dark.ts` **58,393 B** / `src/blackA.ts` **993 B** / `src/whiteA.ts` **1,065 B** / `src/index.ts` 101 B。

**实取的四张中性 12 档表**（逐字抄自 `light.ts` / `dark.ts`）：

| 族 | 1→12 档 hex | 实算 hue 域 | 实算 chroma 域 |
|---|---|---|---|
| light **slate**（偏蓝） | `#fcfcfd #f9f9fb #f0f0f3 #e8e8ec #e0e1e6 #d9d9e0 #cdced6 #b9bbc6 #8b8d98 #80838d #60646c #1c2024` | 210.0–240.0 | **1.0–13.0** |
| light **gray**（纯中性） | `#fcfcfc #f9f9f9 #f0f0f0 #e8e8e8 #e0e0e0 #d9d9d9 #cecece #bbbbbb #8d8d8d #838383 #646464 #202020` | 0.0 | **0.0** |
| light **sage**（偏绿） | `#fbfdfc #f7f9f8 #eef1f0 #e6e9e8 #dfe2e0 #d7dad9 #cbcfcd #b8bcba #868e8b #7c8481 #5f6563 #1a211e` | 绿相 | 与 slate 同量级 |
| light **mauve**（偏紫） | `#fdfcfd #faf9fb #f2eff3 #eae7ec #e3dfe6 #dbd8e0 #d0cdd7 #bcbac7 #8e8c99 #84828e #65636d #211f26` | 紫相 | 同 |
| dark **slate** | `#111113 #18191b #212225 #272a2d #2e3135 #363a3f #43484e #5a6169 #696e77 #777b84 #b0b4ba #edeef0` | 210.0–240.0 | **2.0–15.0** |
| dark **gray** | `#111111 #191919 #222222 #2a2a2a #313131 #3a3a3a #484848 #606060 #6e6e6e #7b7b7b #b4b4b4 #eeeeee` | 0.0 | 0.0 |

**三个形状读数（这些才是可借的东西）**：

1. **同一档号 = 同一用途，与明暗无关**。从值域可反推：`1–2` 页面/卡片底、`3–6` 填充与分隔、`7–8` 加重分隔、`9–10` 实心控件、`11` 次要正文、`12` 主要正文。dark 侧 slate 值从 `#111113` **递增**到 `#edeef0` ⇒ **不是反色，是重取**，而“12 恒为正文”这个不变量保住了。
2. **“中性色”不是一个灰阶而是并列五族**（gray / slate / sage / mauve / olive），同一档号上明度对齐、**只差色相**（slate11 `#60646c`  vs sage11 `#5f6563` vs mauve11 `#65636d` vs gray11 `#646464`）⇒ “微染”在 Radix 是**选族**而不是把 gray 加蓝。
3. **alpha 变体是整另两枚令牌件**：`blackA.ts` 全文 = `blackA1…A12` 为 `rgba(0,0,0,0.05 → 0.95)` 的**单调递增 12 档**；而色系自带的 `grayA1: "#00000003"` 是 8 位 hex alpha。⇒ 本件 §1.2「不写 `rgba()` 进组件、alpha 做独立令牌」在此得到第二个形状佐证（第一个是 §4 的 Radix 目录清单，本批把**体量与内容**补上了）。

### 11.3 VitePress（**MIT**，stars **18,446**）——同一条路的已走完版

全仓 `.css` **13 件**（无 Tailwind / 无 CSS-in-JS）。关键三件：`styles/vars.css` **19,289 B / 649 行**（集中令牌面）/ `styles/components/vp-doc.css` **13,703 B / 627 行**（**单独一个文件只管正文排版**）/ `styles/fonts.css` **15,144 B**。

令牌族计数（`vars.css` 实跑 `Select-String`）：`--vp-c-` **227** / `--vp-shadow-` **5** / `--vp-z-index` **7** / **`--vp-radius` 0** / `rgba(` **20**。

**实取的三层同形证据**（L0→L1→L2 本件 §1.2 不是自创）：

```css
--vp-c-gray-1: #dddde3;   /* light  */   --vp-c-gray-1: #515c67;  /* dark —— 重取不是反色 */
--vp-c-gray-2: #e4e4e9;                  --vp-c-gray-2: #414853;
--vp-c-gray-3: #ebebef;                  --vp-c-gray-3: #32363f;
--vp-c-gray-soft: rgba(142, 150, 170, 0.14);   /* dark 侧 α 也重取：rgba(101,117,133,0.16) */
--vp-c-default-1: var(--vp-c-gray-1);    /* L2 alias 指回 L0 ⇒ 本件 §1.2 的 L2 同形 */
--vp-c-neutral: var(--vp-c-black);       /* :root */   --vp-c-neutral: var(--vp-c-white);  /* .dark ⇒ 同键双套 */
```

**排版读数**（`vp-doc.css` 实取，本件 §1.5 原来没有这几项）：正文 `.vp-doc p { line-height: 1.75; margin: 1rem 0 }`；标题字距**随字号变负**（`2rem`/`1.75rem` 行用 `-0.02em`，`1.25rem`/`1.125rem` 行用 `-0.01em`）；标题行高比正文紧（`1.25–1.43`）。

⚠ **两条“想借但借不到”的如实读数**：① `vp-doc.css` 里 **grep 不到给正文的 `max-width`**，行宽是靠 `--vp-layout-max-width: 90rem` + 固定列实现的 ⇒ 所以下面 §11.5 那条「正文行宽上限」是**本件自定，不是借来**的；② `--vp-radius` 计数为 **0**（它的圆角散在组件里写）⇒ 本件把 `--radius-*` 做成令牌在这点上**严于 VitePress**，不得拿它当“我们多余”的证据。

### 11.4 本地实算：中性色「成族性」体检 + 候选替换的对比度重算

脚本在临时目录（不入库，判据本体在下面，拿不到脚本也能复算）。**先自证探针**：`coef-sum=1.0000` / `cr(黑,白)=21.00` / `cr(红,白)=4.00` / `#1f2937 on #ffffff = 14.68`（与 §6 既有读数**逐字相同**）⇒ **4/4 全杀**，算式没漂，下面的新读数才可信。

**判据本体（复算只需这三条）**：

- 相对亮度系数 `0.2126 / 0.7152 / 0.0722` —— ⚠ 末项是 `.0722`，写成 `.0716` 或 `.7216` 是这类脚本最常见的错，且**症状是“所有读数悄悄偏低”而不是报错**，探针里那条 `21.00` 就是专门拦它的。
- 彩度 `C = max(R,G,B) − min(R,G,B)`（量纲 0–255）；色相 `H` 取 HSL 定义。
- 「成族」判据 = 所有中性令牌的 `H` 落在同一色相带，本批用 `[210, 250]`（蓝相带）。`C = 0` 者（纯白/纯灰）**没有定义色相**，单列不计越带。

#### 11.4.1 本批第一条结论是**证伪我自己上一轮的口头建议**

上一轮我说「中性色加微染（往灰里掺一点蓝，页面立刻显贵）」。实算**推翻它** —— 现有色板**早就是蓝相微染族**：

| 主题 | 令牌 | hex | 实算 `H` | 实算 `C` | 在带 |
|---|---|---|---|---|---|
| light | `--text-1` | `#1f2937` | 215.0 | 24.0 | ✅ |
| light | `--text-2` | `#6b7280` | 220.0 | 21.0 | ✅ |
| light | `--text-3` | `#9199a3` | 213.3 | 18.0 | ✅ |
| light | `--bg-page` | `#f6f7f9` | 220.0 | 3.0 | ✅ |
| light | `--bg-surface` | `#ffffff` | 0.0 | **0.0** | 无定义色相（纯白，不算越带） |
| light | `--bg-raised` | `#fafbfc` | 210.0 | 2.0 | ✅（压带边） |
| light | `--border-decor` | `#d8dee9` | 218.8 | 17.0 | ✅ |
| light | `--border-control` | `#7d8794` | 213.9 | 23.0 | ✅ |
| dark | `--text-1` | `#e6edf3` | **207.7** | 13.0 | ❌ 越带 **2.3°** |
| dark | `--text-2` | `#8b949e` | 211.6 | 19.0 | ✅ |
| dark | `--text-3` | `#6e7681` | 214.7 | 19.0 | ✅ |
| dark | `--bg-page` | `#16191d` | 214.3 | 7.0 | ✅ |
| dark | `--bg-surface` | `#1c2128` | 215.0 | 12.0 | ✅ |
| dark | `--bg-raised` | `#22262d` | 218.2 | 11.0 | ✅ |
| dark | `--border-decor` | `#30363d` | 212.3 | 13.0 | ✅ |
| dark | `--border-control` | `#6e7681` | 214.7 | 19.0 | ✅ |

读数定性：light **8 枚里 7 枚在带**，唯一“越带”的是纯白（`C=0`，本来无定义色相，不构成破族）；dark **8 枚里 7 枚在带**，唯一越带的 `--text-1` 只差 **2.3°**，肉眼与任何工具都分不出。⇒ **这条建议作废：动它是零收益甚至负收益改动（会连带重算 §1.3 整表）。** 成因也顺手记下来，免得下次再误判：这套色值是从 `console.html` 现状继承的，而 Primer / Tailwind 的 gray 阶**本身就是蓝相**（`#1f2937` = Tailwind `gray-800`）⇒ 拿它当“中性灰”时，微染已经在里面了。

#### 11.4.2 第二条证伪：**Radix 的表不能整族照搬**

候选 = light 侧取 `light-slate` 12/11/10，dark 侧取 `dark-slate` 12/11/8：

| 主题 | 令牌 | 现值（CR） | Radix 档 | 候选值 | 候选 CR | 门槛 | 判定 |
|---|---|---|---|---|---|---|---|
| light | `--text-1` | `#1f2937`（14.68） | slate12 | `#1c2024` | **16.39** | ≥4.5 | ✅ 且更优 |
| light | `--text-2` | `#6b7280`（4.83） | slate11 | `#60646c` | **5.94** | ≥4.5 | ✅ 且余量 +1.11 |
| light | `--border-control` | `#7d8794`（3.64） | slate10 | `#80838d` | **3.78** | ≥3.0 | ✅ |
| dark | `--text-1` | `#e6edf3`（13.70） | slate12 | `#edeef0` | **13.94** | ≥4.5 | ✅ |
| dark | `--text-2` | `#8b949e`（5.26） | slate11 | `#b0b4ba` | **7.77** | ≥4.5 | ⚠ 过（见下） |
| dark | `--border-control` | `#6e7681`（3.52） | slate8 | `#5a6169` | **2.58** | ≥3.0 | ❌ **FAIL** |

两条定性：

1. **硬失败一条**：Radix dark `slate8` 拿去勾控件边界 = **2.58 < 3.0**，SC 1.4.11 当场塌。根因不是 Radix 错，是**它的档号服务它自己的用途**（8 档定位是“加重分隔线”，从来不承担“控件边界可辨识”）。**现有值 `#6e7681`（3.52）在这一格上比借来的值更对。**
2. **层次被压扁**：主/次文本的对比度比值，light 从 14.68/4.83 = **3.04×** 变 16.39/5.94 = **2.76×**，dark 从 13.70/5.26 = **2.60×** 变 13.94/7.77 = **1.79×** ⇒ 全部达标，但 `--text-1` 与 `--text-2` 的**视觉层次差变小**，而 §1.3 的分层就是靠这两档拉的。这不是判据红，是**质量退化**，也得算不搬的理由。

⇒ 本节结论一句话：**借 Radix 的“分层纪律”（§11.5 第 1 项），不借它的 hex。** 这与 §4 那格“借形态与纪律，不借代码与品牌资产”是同一个口径，只是这批第一次有了**能证伪照搬方案的具体读数**。

#### 11.4.3 底色分层的实算：两主题都不成立，不只是 dark

`cr(#fafbfc, #f6f7f9)` = **1.03**（light）/ `cr(#22262d, #16191d)` = **1.16**（dark）。设计件 §1.5 阴影那行现在只把「靠 `--border-control` 分层」写成 **dark 专属例外**（“暗底下投影几乎不可见”），但浅色侧底色差只有 **1.03:1** —— 远低于任何可辨识阈值。⇒ 那条不该是例外，要升级为**两主题通用**。这是本批**唯一**由实算推出、并因此改动设计件正文的结论。

同向佐证（`console.html` 实取，全文 346 行）：`box-shadow` **0 条** ⇒ 参照物自己**从来没有用投影分过层**，它的卡片分层全靠 `--line` 边框。这条读数和上面那个 1.03 是两回事（一个是“该不该用”，一个是“底色差够不够”），但指向同一处置。

### 11.5 真正借到的：四条纪律 + 一条形状，全部零依赖

“借到了什么”必须和“没借到什么”同批写，否则本节会被读成“抄了一张色板”。

| # | 借到 | 出处（实取原文） | 落点 | 零依赖？ |
|---|---|---|---|---|
| 1 | **档号即用途，与明暗无关**（1–2 页面/卡片底、3–6 填充与分隔、7–8 加重分隔、9–10 实心控件、11 次要正文、12 主要正文），且 dark 是**重取不是反色**（slate 从 `#111113` **递增**到 `#edeef0`，而“12 恒为正文”这个不变量保住了） | Radix `light.ts` / `dark.ts` 四张 12 档表（§11.2） | 设计件 §1.2 L0 补一句「档号↔用途」映射，实现期不必猜该拿哪一档 | ✅ 纯文档 |
| 2 | **字距随字号变号**：小字正字距、大字负字距 | **两个独立来源同形**：VitePress `vp-doc.css` 给 `2rem`/`1.75rem` 用 `-0.02em`、`1.25rem`/`1.125rem` 用 `-0.01em`；而 `console.html:18` 对 13px 小标题用 `letter-spacing:.02em`（全文**唯一**一条）⇒ 恰好是同一条规律的另半个轴 | 设计件 §1.5 **新增「字距」一行**（此前该维度完全空缺） | ✅ 一个 CSS 属性 |
| 3 | **投影是双层叠加不是单层**（近层压边 + 远层扩散） | VitePress `vars.css`：`--vp-shadow-1: 0 1px 2px rgba(0,0,0,.04), 0 1px 2px rgba(0,0,0,.06)`、`--vp-shadow-2: 0 3px 12px rgba(0,0,0,.07), 0 1px 4px rgba(0,0,0,.07)`（实取 **5 枚里第 5 枚为空声明**，即它自己也没用满） | 设计件 §1.5 阴影那行写明「双层叠加形状」，**档数仍 ≤2**，不越 §1.5 上限 | ✅ `rgba()` 只写在 `tokens.css`，不破 §1.2「组件不写 `rgba()`」 |
| 4 | **正文行高往松走** | VitePress `.vp-doc p { line-height: 1.75 }`；参照物 `console.html` 全文 `line-height` **0 条** ⇒ 它“挤”不是风格选择，是**根本没设**（浏览器 `normal`） | 设计件 §1.5 新增「行高」行并新立 `--lh-tight 1.5` / `--lh-body 1.7` 两枚令牌。**⚠ 取值 1.7 不是借来的**：它比 1.75 紧，理由是灯阵/事件行是密集数据面而 VitePress 是文档面 —— 这一格属**本件自定**，不得拿本项当它的出处（本项只供“往松走”这个方向与 1.75 这个参照值） | ✅ |
| 5 | **单独一个文件只管正文排版** | VitePress `styles/components/vp-doc.css` 627 行 / 13,703 B 只做这件事（全仓 `.css` 仅 13 件） | **佐证**设计件 §1.1 `base.css` 的职责边界，不产生新改动 | — |

**明确借不到的（口径与 §4 一致）**：

- **Radix 的 hex 一个都不搬** —— §11.4.2 那条 dark `--border-control` **2.58 FAIL** 就是照搬的代价，这一条把“不搬”从口味升级成了判据。
- **VitePress 没有 `--vp-radius`**（实取计数 **0**，圆角散在组件里）⇒ 本件 `--radius-*` 三档**严于**它，不得反拿它当“我们多余”的证据。
- **VitePress 正文 `max-width` grep 不到**（行宽靠 `--vp-layout-max-width: 90rem` + 固定列）⇒ 本件 §2.1 的正文行宽上限是**自定，不是借来**。
- **许可不是这里的理由**：VitePress 实取 `spdx_id=MIT`（stars **18,446**），Radix Colors 实取 `spdx_id=MIT`（stars **1,725**，全仓仅 **22 条目**）⇒ 搬色值在许可上**合法**，“不搬”是**判据决定的**。这句必须写在档，否则 §11.4.2 会被误读成“怕 License”。

### 11.6 本批随动落点（设计件改了哪几行）

| 设计件位置 | 改了什么 | 驱动力 |
|---|---|---|
| §1.2 L0 行 | 补「档号↔用途」映射一句 + dark 重取不反色 | §11.5 第 1 项 |
| §1.3 `--bg-raised` 行 | 「浅色主题的分层靠 border」→ **两主题通用**，并把 `1.16` 那条 dark 读数一起写明 | §11.4.3 |
| §1.3 表后 | 新增一条「色板已在蓝相带，不得再提『加微染』」的读数注记 | §11.4.1（防后人重复我上一轮那个误判） |
| §1.5 字阶行 | 行高从**写在字阶行里的散文数值**收口为两枚令牌 `--lh-tight 1.5` / `--lh-body 1.7`（正文从 1.6 放宽），并记参照物 `line-height` **0 条**与只用过 6 个字号 | §11.5 第 4 项 + §11.4.3 |
| §1.5 **新增「行高」行** | 独立一行承载 `--lh-*`，并明写「取 1.7 而不取 1.75 是本件自定」 | 上表的 ⚠ 那格（防后人拿 VitePress 的 1.75 米反过来改本件） |
| §1.5 新增「字距」行 | `--ls-tight -0.01em` / `--ls-head -0.02em` / `--ls-wide .02em`，**≤3 档** | §11.5 第 2 项 |
| §1.5 阴影行 | 写明双层叠加形状；分层依据从 dark 专属改为两主题通用 | §11.5 第 3 项 + §11.4.3 |
| §1.2 L1 行 | 令牌族清单补 `--lh-*` 与 `--ls-*` 两族（否则新增令牌不在「组件唯一可消费层」里 = 自矛盾） | 与上三行同步 |
| §1.4 图标行 | 补两条描边一致性约束（`stroke-linecap` / `stroke-linejoin` 全批同取 `round`），并明标**本件自定、不是借来** | 本批外部参照只给到「图标继承 `currentColor`」这一层，如实登记 |
| §6 断言 4 | 加两个子句：裸 `line-height: <数字>` / 裸 `letter-spacing` 即红（**不开新断言号**）；反证表同步加一行逐子句反证 | 新立令牌族按《架构决策原则》三层齐备必须配门禁，否则只是散文约定 |
| §1.5 标题 | 由「字阶、间距、圆角、阴影、动效」改为含「字重、行高、字距」（原标题漏列了已存在的字重行，本批一并补齐） | 顺手修文档自己的账面不同步 |
| §4 第 3 项 | 出处指针补本件 §11（此前只引 §4 目录清单，现在有了数值表与算式） | — |
| §9 默认值 | 新增 ⑥「排版三值（行高 1.7 / 字距三档 / 双层阴影）」含一句话推翻的代价 | 这三条是**主张**不是判据，必须进默认值表而不是正文当既成 |
| §9 排除项 | 新增一条：不做 perceptual diff / 不做 CJK 回落脚本下的行高实测 | §11.7 未覆盖清单 |

**未被本批改动的（同样重要，免得被读成“整份色板重做了”）**：§1.3 全部 hex **一个都没改**、tint 八色**没改**、事件分色集**没改**、灯阵 30 字段派生口径**没改**、`--fs-*` 五档封顶**没动**（只是补了字距这个新维度）。§11.4.1 那条证伪的直接后果就是“色值表原样”。

### 11.7 强度分档与未覆盖清单

- **已取证（可直接引用）**：Radix / VitePress 的 license、stars、条目数、文件字节数、四张 12 档 hex、shadow 原文、行高原文、字距原文 —— 全部 `gh api` / `Select-String` 现取，命令在 §11.1。
- **已实算（判据本体在档）**：成族性 `H`/`C` 16 枚、六条候选对比度、两个底色 `Δ`、探针 4/4 —— 脚本不入库但三条判据全写在 §11.4。
- **仍是主张（未取证）**：这五条纪律搬过来“页面会更好看”是**判断**，其强度来自两个独立来源同形（VitePress 负字距 / console 正字距），不来自读数。**V1–V7 本批仍一条未取**：没建 `web/`、没写一行 CSS、没渲染过一帧、没做过 perceptual diff。
- ⚠ **本批新引入的一条已知盲区（写进 §9 排除项）**：正文行高 1.6→1.7 是在**英文 Latin1 子集**下算的形状，而 §1.4 已定**中文不打包字体** ⇒ CJK 回落脚本（Noto Sans CJK SC / 微软雅黑）的行盒度量与 Plex 不同，混排行的实际视觉行高**未实测**。这不是判据风险（行高不参与 WCAG 对比度），是观感风险，属 V1 截图那格才能收的账。

---

## 12. 同日第五批（POC 落地 + 灯阵拆独立页 + 四份文档回写）的复跑台账

**触发链**：用户「先出个最小 poc」→ 三轮定位质疑（为何是问数工作台 / 是否按能力分家 / 哪个更符合企业级）→ AskUserQuestion 拍板「**灯阵拆成独立页** + 控制台形态」→ 本批把已显式登记的欠项逐项清账（四份文档回写 + F1–F8 落进规范本体 + 本目录随拆页更新 + 分支模型建议）。

**本批不再是零产品代码**：样式三件 + 两个静态宿主页 + Node 门禁脚本已在工作树。但**后端目录 diff 仍 0 行、未 `git add`、未提交、未推送、HEAD 仍 = `d140f91f`**。

### 12.1 环境坐标

| 项 | 实取值 |
|---|---|
| HEAD / 分支（G0） | `d140f91f` / `feat/nl2sql-ttl-and-006-slim`（无 upstream） |
| 静态预览 | `node .tmp-scratch/ap-visual/serve-poc.mjs` 挂 :8123；`Invoke-WebRequest` 实取三个 URL 全 **200** |
| 本机 | Windows PowerShell 5.1，无 `make`；`.ps1` 需 `powershell -ExecutionPolicy Bypass -File` 才跑得住（本窗实踩：不带该开关直接被执行策略拦下） |
| 取数脚本 | 本件 §10.2 那一张**八道表**的脚本本体（`.tmp-scratch/ap-visual/gates4.ps1`）**判据一字未改**，只重跑 |

### 12.2 十道台账（原八道 + 样式层新增两道）

⚠ **为什么从八道扩到十道**：拆页后多了一个只属样式层的门禁（`check-tokens.mjs`）与它的反证（变异脚本）。这两道不碰 Python，原八道一道也拦不到它们 ⇒ 不新增这两道，「样式层已有门禁」就是句无读数的声明。

| # | 命令 | 第四批（§10.2） | **第五批实跑** | 差值定性 |
|---|---|---|---|---|
| 1 | `git diff --name-only d140f91f -- applications packages scripts tests eval deploy Makefile pyproject.toml` | 行数 **0** | 行数 **0** | **不变** ⇒ V7 的正身：拆页只动 `web/` |
| 2 | `git status --short --untracked-files=all \| Where-Object { $_ -notmatch 'docs/' }` | **空** | **7 条**，全在 `web/` 下（README / poc / poc-health / check-tokens / base.css / events.css / tokens.css） | **预期内变化**：本批首次不再是「全零」形状 ⇒ 基线换为联合判据「① = 0 行 **且** ② 只含 `web/`」 |
| 3 | `Test-Path web` | **False** | **True** | 预期内变化（同上；仍**未 `git add`**，所以七条全是 untracked） |
| 4 | `uv run --no-sync python scripts/check_doc_sync.py` | rc=**0**（0 警告） | rc=**0**（`✅ 文档同步校验通过（0 警告）`） | **不变** ⇒ 本批未写任何指向未入库路径的**顶层三文档**引用（根 README 一行未动） |
| 5 | `uv run --with ruff ruff check .` | rc=**0** | rc=**0**（`All checks passed!`） | 不变（本批仍未动 `.py`；两个取证脚本住在 gitignored 目录，这道不扫它们 —— 同 §10.2 那条告警） |
| 6 | 就地引用边自查（四份 docs 文件，脚本同 §10） | `total=139 / unique=69 / unresolved=5` | `total=**139** / unique=**69** / unresolved_unique=**5**` | **三值逐字不动** ⇒ 本轮往四份文档里拆页改写、新增两个全表与一个 §11，**新增 0 条 docs 引用边、0 条断链**（做出来的：随动段一律用中文指代，不重抄文件名） |
| 7 | 提及数（令牌**不带** `.md`，`git grep -o --untracked`） | 8 / 9 / 11 | 视觉件 **8** / 取证件目录名 **9** / 工单件 **11** | 三值不动。⚠ 口径同 §10.2：这是**当前工作树快照**，不是常量 |
| 8 | 表格完整性（行首竖线而行尾非竖线） | 四份各 **0** | 四份各 **0** 命中 | 不变（本轮新增七张表，逐行核过） |
| 9 | **（新）`node web/scripts/check-tokens.mjs`** | 无此道 | rc=**0**；定义 **91** / 引用 **91**；派生集 **事件 12 类 / 字段 30 个**；断言 6 三行 = 事件图例 **12/12**、分组字典 **30/30**、说明字典 **30/30** | 新道，**首次取数**。脚本内仍不出现 12/30 这两个硬常数（从源派生） |
| 10 | **（新）`node .tmp-scratch/ap-visual/mutate-v1.mjs`** | 无此道 | **10/10 格命中**，全撤销后终态 rc=**0**（失败段逐字见 §12.3） | 新道，**首次取数**。上一批是 7 格，本批 +3 格只为反证「扫描面真含第二页」。⚠ **本行那个「10 格」自第六批起是历史值**（现值：反证格全数有效 **+ 探针 1 格**，读数在 §13.2；格数一律以脚本 `MUTANTS` 为准，不在散文里抄） |

**第 6 条这一格在第五批比前四批重要**：文档回写本身就是「往文档里加路径」的动作，加一条就推一个数 ⇒ 三值逐字不动是下笔时刻意控制的结果（可复现口径：指代三份互指文档一律用中文，只写小节号与 §11/§12 这类本件内锚）。

### 12.3 十格变异的逐格读数（第五批全量重跑，不是引上一批）

| 变异格 | 变异后 rc | 是否命中该格断言 | 撤销后 | 失败段首行（实抄） |
|---|---|---|---|---|
| 断言1 色值字面量 | rc=1 | 命中断言1 | 复跑 rc=0 | `断言1 \web\src\styles\base.css 出现色值字面量：#ff0000` |
| 断言2 引用未登记 | rc=1 | 命中断言2 | 复跑 rc=0 | `断言2 引用了未登记令牌 --nope-9` |
| 断言3 孤儿令牌 | rc=1 | 命中断言3 | 复跑 rc=0 | `断言3 孤儿令牌 --orphan-probe（登记了无人引用…）` |
| 断言4 裸间距 | rc=1 | 命中断言4 | 复跑 rc=0 | `断言4 \web\src\styles\base.css padding:7px 用了裸尺寸，只允许 var(--sp-*)` |
| 断言5 dark 双写漂移 | rc=1 | 命中断言5 | 复跑 rc=0 | `断言5 dark 双写漂移（1 条）：` |
| 断言6 字典缺项 | rc=1 | 命中断言6 | 复跑 rc=0 | `断言6 事件图例字典 缺项（派生自源但字典没有）：done` |
| 断言6 字典多项 | rc=1 | 命中断言6 | 复跑 rc=0 | `断言6 事件图例字典 多项（字典有但源已不产出）：bogus_evt` |
| **断言1 独立灯页色值（新）** | rc=1 | 命中断言1 | 复跑 rc=0 | `断言1 \web\poc-health.html 出现色值字面量：#ff0000` |
| **断言6 灯阵缺项（新）** | rc=1 | 命中断言6 | 复跑 rc=0 | `断言6 /health 分组字典 缺项（…）：langfuse_enabled, langfuse_ready, otel, otel_status` |
| **断言6 灯阵多项（新）** | rc=1 | 命中断言6 | 复跑 rc=0 | `断言6 /health 分组字典 多项（字典有但源已不产出）：bogus_lamp` |

⚠ **两格读数里藏着一个值得记的事**：删「观测」组那一格报出的是**四个**字段名（`langfuse_enabled / langfuse_ready / otel / otel_status`）而不是一个 —— 删整组比删单字段更容易被门禁抓住，这是**期望集从源派生**的直接好处；写死的版本在这一格只会报「少了 1 个」甚至凑巧绿。

⚠ **反证表十行 ≠ 脚本十格**（不得拿两边都是 10 当作已对齐）：脚本对断言 4 只反证了「裸间距」一个子句，`font-weight: 700` / 裸 `line-height` / 裸 `letter-spacing` **三个子句无对应变异格**。要补就补脚本格，**不得反过来把表缩到与脚本齐平**（那正是《验证策略》红线里「收窄断言凑绿」的变体）。

⚠ **本行到第六批已随动**：那三个子句在 2026-10-31 补上了脚本格（见 **§13.2**），本段作为**第五批当时的账面快照**保留，不得当现值引。

### 12.4 两个页面的浏览器量测读数（同源 iframe 1440×900，**不是实拍**）

⚠ 先声明强度：本机实拍通道坏了（§12.7），本节全部数是 **DOM / computedStyle 量测**。量测能答宽度、列数、溢出、计算值，**答不了「看上去对不对」**。

**对话页**（`web/poc.html`，拆页后）：

| 项 | 实测 | 判读 |
|---|---|---|
| 两栏宽 | `579.39px` / `737.41px` | 比值 **0.786** = 1.1/1.4 目标比值 ⇒ 继承来的比例**在 `minmax(0,…)` 下才成立** |
| `#lamps` | **null** | 灯阵 DOM 已整批移出对话页（不是隐藏，是不存在） |
| `.ev` 事件行 | **13 条全可见** | 12 类 + 1 条未识别事件行，无静默吞掉 |
| 链接选中态 | `a.btn` 无下划线；`aria-current="page"` 背景与其余不同 | 本批新补：读代码发现 `base.css` **此前没有任何 `a` 规则** ⇒ `<a class="btn">` 会渲染成默认下划线蓝（**门禁查不出这一型**：令牌都登记了，缺的是规则本身） |
| console | **0** 报错 | 无未捕获异常 |
| 横向溢出（宽视口） | 视口 1440 ⇒ `clientWidth` **1425** = `scrollWidth` **1425** | 宽档无溢出。⚠ **窄档（768 / 375）那条「无横向滚动」判据属 V4 实拍，本批未取**（§12.7） |

**灯阵独立页**（`web/poc-health.html`）：

| 项 | 实测 | 判读 |
|---|---|---|
| 分组 | **5 组**，每组标题不重复 | 与 §1 的两层字段全集分组一致 |
| 容器宽 | **1328.80px** | 独立页才有这个宽度（对话页第三栏只有 372.8px） |
| 列数 / 卡宽 | `auto-fill` 排 **4 列**，30 张卡全 **319.80px** | **319.80 ≥ 260 地板** ⇒ 「3 列 × `minmax(260px,1fr)`」这个约束本身成立，先前只是放错了页面 |
| 灯名溢出 / 断行 | **0 / 0** | 30 个字段名原文逐字显示不撑破卡片 |
| 5 列可行性 | 需 `5 × 260 + 4 × 8 = **1332px**`，容器 **1328.80px** | **只差 3.2px** ⇒ razor-edge：改一点 padding/gap 就翻列，任何引用「4 列」的下游陈述都该绑 rev |
| 「一屏读完 30 盏」 | `scrollHeight` **1406** vs `innerHeight` **900**，差 **506px** | **不成立**（对话页那栏更不可能）。这是规范内部自相矛盾 ⇒ **本批未改判据**，三个处置选项交拍板 |
| `.grid` | 不存在 | 独立页不继承对话页骨架（不是靠覆盖隐藏，是没那条规则） |

### 12.5 一次被实测推翻的**自纠**：`false` 与 `muted` 的形状差

上轮我认为「空心圆（`--radius-pill`）vs 空心方（`--radius-sm`）」已满足「不同形状」。本轮拿 computedStyle 实比，**推翻自己的修法**：

| 档 | `background` | `border` | `border-radius`（声明值 → **实取值**） |
|---|---|---|---|
| `false`（`.dot--off`） | transparent | `2px solid` | `999px` → **5px**（被盒子钳制：内切上限 = 短边一半，而状态点是 **10×10px**） |
| `null`（`.dot--null`） | `--status-warn` 实心 | `1px solid` | `999px` → **5px** |
| 非布尔（`.dot--muted`，上轮版） | transparent | `2px solid` | `4px`（`--radius-sm`） |

⇒ `off` 与 `muted` 三项 computedStyle **两项全同、半径只差 1px = 边长的 10%**，不可辨。现取 `border-radius: 0`（方）与 `999px`→5px（圆）拉开到两端。**纪律落为视觉件 §11 F7**：形状通道的可辨量要拿**实际像素**比，不能拿令牌名比 —— 「两个令牌不同」不等于「两种形状不同」。

### 12.6 上一轮那条 `834 > 400` 横向溢出：**测量假象**，且本批之前从未入库

⚠ **本节必须把两件事分开说，否则会写成一句不存在的「改错行」**：

1. **本批之前，它不在任何入库文件里**（这条是可复跑取证，命令必须写对）：`git grep -n 834 HEAD -- '*.md'` ⇒ HEAD 树内**仅 1 处命中**，且命中的是已入库的那份 09-22 技术债件第 56 行里提交号 `cd5834cb` 的**无关数字子串**，与本读数无关。库里没有可订正的错行。
   ⚠ **取证口径的一条自我订正**：上一版本节写的是「本批用 `Select-String` 在本件全文 851 行里查 `834`：0 命中」——**这句不可复跑**，因为本件与视觉件**都还没入库**（`git status --short --untracked-files=all` 里现在是两条 `??`），§12 落笔前的旧版没有快照可回溯，只能作为本批的账面声明读，不能当读数。可复跑的是上面那条 HEAD 面命令 —— 「从未入库」这个词必须按 `git ls-files` / `HEAD` 口径取证，不按本机文件系统（与 AGENTS.md《验证策略》那条 doc-sync 存在的同款坑：以 FS 为基准会把自己喂绿）。
   ⇒ 本节的性质 = **首次登记一个从未入库的错误读数**，不是订正一条已入库的错行。
   **本批之后的形状**（同一命令换 `--untracked`）：`git grep -n --untracked 834 -- '*.md'` = **8 命中 / 6 文件**，除去那条无关子串 ⇒ **7 处 / 5 份文件**（本件、视觉件、工单件、顶层 docs 索引、`web/README.md`），**全部是「此读数系测量假象」的作废声明措辞**，没有一处把它当缺陷读数留着。⇒ 「不留错误读数」的判据是**语义形状**（残留的每一次命中都必须指向作废声明），不是命中次数为 0。
2. **证伪方式（对照实验）**：同一页、同一 CSS，在「刚把宿主 iframe 宽度改到 400 后直接读数」与「改宽后触发一次重布局再读数」两种取法下给出不同结果 —— 前者 `scrollWidth` 停在**上一次宽档的 834**（页面尚未按新宽度重排，读的是旧布局残留），后者与 `clientWidth` 齐平 ⇒ **834 > 400 不是页面装不下东西，是测量工具自己的遗留**。
3. **落为判据**（视觉件 §11 F6）：几何读数必须在「刚设过视口、已触发重布局」的**同一帧**取。跳帧取到的数不得入库，因为它测的是工具而不是页面。

⇒ 上一轮基于该读数提的那条「修复」本批**未进规范正文**，也不得留在任何下游陈述里。

### 12.7 V4 实拍判据：**本批未达（阻塞）**

用户指令明写「这条必须如实标注为未满足，不得写成已过」。实取值：

| 项 | 读数 |
|---|---|
| 浏览器子代理实拍请求 | 失败，报 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`（viewport **340×454**、`visible=false`、`attached=false`） |
| 能否拍出 6 张（light/dark × 1280/768/375） | **不能，一张都拍不出** |
| 替代手段 | 同源 iframe 1440×900 下的 DOM / computedStyle 量测（即 §12.4） |
| 替代手段能回答 / 不能回答 | 能：宽度、列数、溢出、计算样式。**不能**：「看上去对不对」、字体回落的实际观感、dark 主题下的整体阅读对比 |
| V4 判定 | **未达（阻塞在本机工具链，不是产品缺陷）**。要收这格账需一台能控制真实视口的机器 |

⇒ 同时修正 §10.2 末句的口径：「V1–V7 仍一条未取」从本批起**不再成立**（本批已取 V1/V2/V5/V7 的读数、V3/V6 到形状层），但**不得**因而把 V4 读成已过。

### 12.8 本批顺带查出的一次**文档自相矛盾**：PR-5

视觉件 §8 第四批那行原写「工单件侧随动包含新增的 **PR-5** 工单行」。逐处核：

| 位置 | 原陈述 | 实测 |
|---|---|---|
| 工单件 §7 工单表 | 只到 **PR-4**，无 PR-5 行 | `Select-String 'PR-5'` 在该件**仅命中 PR-0 行里那句「不建 PR-5」** |
| 视觉件头部 L6 | 「**未新增工单、未建 PR-5**」 | 与上表一致 |
| 视觉件 §8 第四批行 | 「新增的 PR-5 工单行」 | **与两处矛盾 ⇒ 错的是这一行** |

已就地订正（改为「随动在 §13.4 履行表」并写明本行原陈述为错、第五批核正）。这一型值得记的理由：**它是上一批自己写的随动登记句**，不是外部错指 —— 随动表里写的「已改了 X」若未回头对照被改件的实际行数，下一批就会拿它当已存事实去引（与 §10.2 那条「计数被本件自己推着走」同族）。

### 12.9 本批四份文档回写的落点清单

| 文档 | 改了哪几处 | 强度 |
|---|---|---|
| 视觉件 | §2.1 拆两视图 + 硬规则三条；§2.2 两条带算式的判据（F2/F3）；§2.3 标题改独立视图 + 三档→四档形状 + F7 半径可辨量；§6 扫描面行 + 断言 6 坐标随动 + 反证表三新格；§7 V4 行标阻塞 + V1–V7 逐道实跑状态；§8 第四批行订正 PR-5 + 新增第五批行；§9 排除项 1 复审登记；§10 复跑命令改①②③ 期望值 + 新增④ 两道；新增 **§11**（F1–F8） | **文档已回写**（不等于已验收） |
| 工单件 | §7 PR-2 行改两栏视图 + 不交灯阵；PR-4 行改独立视图 + 「一屏读完仍未成立」写进工单行 + 四档形状口径；表下注 V 系列由「一条未取」改为逐道状态；§13.4 新增四行（拆页随动 / 未入库错读数首次登记 / PR-5 自纠 / 第五批射程与三道门槛），并把第四批那两行标为「历史快照」；**另新增 §8.1 = 本批分支模型方案**（用户那句「是否要另开新分支」的收口，只给方案未动 git），其取证读数就是本件 §12.11 | **文档已回写** |
| 本取证件 | 新增 **§12**（本节） | 读数已取 |
| 顶层 docs 索引 | §3.9 视觉件行与取证件行重写（含「POC 跑了不等于本件批了」那条边界）；提及数口径段新增第五批复跑说明与「全零形状不再可复现」的基线换形 | **文档已回写**（⚠ 根 README 一行未动：`check_doc_sync.py` 的存在性基准是 `git ls-files`，`web/` 未入库前写进去必红 —— G4 rc=0 已证） |

### 12.10 强度分档与未覆盖清单（字段 4：没跑的部分与原因）

- **已实跑（可直接引用）**：§12.2 十道逐值、§12.3 十格变异逐行（含失败段首行实抄）、§12.4 两页几何量测、§12.5 四档 computedStyle 实比。
- **文档已回写、但未验收**：四份文档的改写属「账面同步完成」，**不等于规范已批**。视觉件仍**待用户点头**，且新增一个开工前置拍板项（「一屏读完 30 盏」的 A/B/C）。
- **未跑（阻塞/越射程，逐项写因）**：
  1. **V4 实拍六张 —— 阻塞**（§12.7，本机视口失联）。**不得读成已过**。
  2. 窄档（768 / 375）的「无横向滚动」判据 —— **未取**，它属 V4 实拍形状（§12.4 只覆盖到宽档）。
  3. 真库 / 真后端流（SSE 消费、`/health` 拉取）—— **未接**，POC 射程外（两个页面上每个数字都是手写假数据）。
  4. `make ci-web` / `make lint` / `make test` —— **未跑**：该 Makefile 目标尚未创建（属 PR-0），且本批未动任何 Python。
  5. 断言 4 的三个子句（`font-weight` / `line-height` / `letter-spacing`）—— 第五批未证有牙。⚠ **本项已于次日第六批收掉**（三格补齐，见 §13.2）；本行保留为第五批快照。
  6. CJK 回落脚本下的行高/字距观感 —— **仍未实测**（§9 排除项 6 那条在册盲区，本批未收）。

### 12.11 分支模型的取证读数（方案本体在工单件 §8，本件只挂证据）

用户上一轮问的「这批改动是否要另开新分支」本批给结论。结论必须先有读数，命令逐字可复跑：

| 项 | 命令 | 本批实取 |
|---|---|---|
| 远端清单 | `git remote -v` | 2 个：`company`（内网 SSH，fetch/push 俱在）+ `github-legacy`（公开脱敏镜像，其 push URL 已被改写为 `DISABLED-no-push` 说明串 ⇒ **禁推**）。**无 `origin`**（照抄 `origin` 只会报 `No such remote`） |
| `company` 远端分支 | `git ls-remote --heads company`（rc=**0**） | **1 条**：`refs/heads/main` @ `fe22794c5a36e855114e2bbf99c0df341b3f695f` |
| 本地分支全表 | `git for-each-ref --format='%(refname:short)｜upstream=%(upstream:short)｜%(objectname:short)' refs/heads` | **8 条**（与工单件 §11.7 那次体检后的 9→8 一致）；其中 3 条 upstream 指向 `github-legacy`，含本地 `main` |
| 本地 `main` 跟的是谁 | `git rev-parse --short main` | `88515cab` = `github-legacy/main` 的 tip ⇒ **本地 main 是公开脱敏镜像树，不得当内网工作的切点** |
| 工作线与 `company/main` 同源否 | `git merge-base HEAD fe22794c` | **rc=1、空输出** ⇒ 无共同祖先，两条异宗历史 |
| 本地 main 与工作线互相领先 | `git rev-list --left-right --count main...HEAD` | **6 / 367**。⚠ 工单件 §11.7 登记的是「6 vs 339」⇒ **该数随工作线增长而变，引用前必复跑，不得直接引档里的旧值** |
| 当前分支 / tip / upstream | `git branch --show-current` + `git rev-parse --short HEAD` | `feat/nl2sql-ttl-and-006-slim` @ `d140f91f`，**无 upstream** |
| 本批账面归谁承载 | `git status --short --untracked-files=all` | **无归属** —— docs 侧 4 项（两条 ` M` + 两条 `??`）+ `web/` 侧 7 项未入库，全部只在工作树，**零 `git add`**（用户红线） |

⇒ 由此三条硬结论（都是读数直接支持的动作，不是口味）：

1. AGENTS.md《分支卫生》的「远端恒 2 分支（`main` + 唯一集成分支）」在**当前仓内没有对应物** —— `company` 只有 `main` 一条，且那条 `main` 与本工作线异宗。⇒ 「唯一集成分支」是**待建项**，建不建 + 首推属 **D2（人拍板）**，不由本批自决。
2. **切点绝不能取本地 `main`**：那是公开脱敏镜像树（带占位符），从它切出去再合回内网，等于拿 `<internal-host>` 这类遮位去当真实值用。
3. 本批 11 项改动**零提交悬在工作树**，越久越难拆成《分支卫生》要求的 <400 行三刀 ⇒ 这是「何时提交」的工期依据，不是「必须提交」的授权。

### 12.12 本批收尾复跑（§12.6/§12.9/§12.11 订正与工单件 §8.1 落笔**之后**的终值）

上面那些台账本身也是文本，它们写下去就有把引用计数推动的风险，所以取完再跑一轮。**终值与 §12.2 那行完全同**，逐项实抄：

| 道 | 终值（本轮） | 与 §12.2 第五批列的差 |
|---|---|---|
| G0 HEAD / branch | `d140f91f` / `feat/nl2sql-ttl-and-006-slim` | 不变（**零提交**） |
| G1 后端目录 diff | lines=**0** | 不变 |
| G2 非 docs 条数 | lines=**7**（`web/` 下 README / poc / poc-health / check-tokens / base.css / events.css / tokens.css，逐条同名） | 不变 |
| G3 `Test-Path web` | **True** | 不变 |
| G4 `check_doc_sync.py` | rc=**0**（`✅ 文档同步校验通过（0 警告）`） | 不变 |
| G5 `ruff check .` | rc=**0**（`All checks passed!`） | 不变 |
| G6 引用边 | total=**139** / unique=**69** / unresolved=**5**，且五条 BAD **逐字同旧值**（三条 adr/00x、故意改坏的夹具 …2026-10-30.mX、docs/plans/README.md；完整带反引号的清单在 §12.2 那一行） | **不变** ⇒ 本批文档大量扩写（含 §12.11 与本行）**未新增一条可匹配的 docs 路径引用**；这是**做出来的**（指代一律用中文、路径不进反引号），不是巧合 |
| G7 提及数 | **8 / 9 / 11** | 不变 |
| G8 表格完整性 | 四份全 **0** | 不变（§12.11 那张八行表未破形） |
| ⑨ `check-tokens.mjs` | rc=**0**：定义 **91** / 引用 **91**；派生集事件 **12** / 字段 **30**；断言 6 三行 **12/12、30/30、30/30** | 不变 |
| ⑩ `mutate-v1.mjs` | **10 格全部有效**（逐格 rc=1、撤销后复跑 rc=0）+ 全撤销终态 rc=**0** | 格 8 标签随脚本内错字一并改正后**重取**，读数不变。⚠ 第五批终值快照，现值见 §13.2 |

⇒ 上一行那句「格 8 标签」补一条本批踩到的错：变异脚本里那格原本叫「健页色值」（错字），而本件 §12.3 把它**照抄**进了台账 —— 错字于是从工具爬进了文档。修正分两头：脚本侧改标签为「独立灯页色值」，**改完重跑变异**再回填台账（不是改完文档就去手写读数），视觉件 §11 F8 行同步。这一型的启示：**实抄不是照搬，抄进去前得先看它本身对不对** —— 上一版台账里那条错字就是“照抄可以免检查”这个错觉的产物。

⚠ **而本节自己又被复跑当场抓了一次**：上面那一行最初把那四条 BAD 路径**写进了反引号**，于是同一轮复跑里 G6 的 total 从 139 跳到 **143**（unique 仍 69、unresolved 仍 5 —— 那四条路径本来就在集合内，只是**边数被本件自己加了 4 条**）。改法 = 把四处改回不带反引号的普通文本，再复跑回到 **139**（本行写的就是改后的实跑值）。⇒ 与本件在册那条「这组数被本件自己推着走」（第三批从 136/68 被推高那次）同族，且它是**同一批里的第二次**。「每完成一组改动就复跑」不是仪式：这一格与上面那条错字都是复跑跑出来的，不是推想出来的。

## 13. 次日第六批（2026-10-31）：把断言 4 的三子句补成有牙格，顺手拿实测探到一条**射程边界**

### 13.1 本批开工时只动了两样

上一批汇报里两条在册欠项中最靠得着的一格（「断言 4 的三个子句未证有牙」）本批闭掉。**只动变异脚本与文档，未动一条断言、未动一个样式值、未动任何后端文件**。开工坐标：时刻 **2026-10-31 07:13:05**（`Get-Date` 实取）、HEAD 仍 `d140f91f`、暂存区仍空。

工具侧一项结构改动（不是凑数）：变异判据从「命中断言号」扩为**「命中断言号 + 命中该子句报出的那段文字」**。理由：断言 4 是**一条带四个子句**的断言，只校断言号会把「触发了同一断言的另一个子句」误读成「这一格有牙」。

### 13.2 新增五格的逐格读数（实抄；§12.3 那张十行表原样有效，不重贴）

| 新增变异格 | 变异后 rc | 判定 | 撤销后 | 失败段里实抄那一行 |
|---|---|---|---|---|
| 断言4 裸间距（本批**补上子句维度**） | rc=1 | 命中断言4·含子句 | 复跑 rc=0 | `断言4 \web\src\styles\base.css padding:7px 用了裸尺寸，只允许 var(--sp-*)` |
| 断言4 非三档字重（子句 font-weight） | rc=1 | 命中断言4·含子句 | 复跑 rc=0 | `断言4 …base.css font-weight:700 只允许 400/500/600（未打包的字重会静默回落）` |
| 断言4 裸行高（子句 line-height） | rc=1 | 命中断言4·含子句 | 复跑 rc=0 | `断言4 …base.css line-height:1.8 只允许 var(--lh-*) / var(--ls-*)（第四批新立令牌族的子句）` |
| 断言4 裸字距（子句 letter-spacing） | rc=1 | 命中断言4·含子句 | 复跑 rc=0 | `断言4 …base.css letter-spacing:0.02em 只允许 var(--lh-*) / var(--ls-*)（同上）` |
| 读不到灯阵字典（fail 口） | rc=1 | 命中断言6·含子句 | 复跑 rc=0 | `断言6 poc-health.html 里读不到 const LAMP_GROUPS（灯阵字典坐标变了，先核对再改门禁）` |

脚本自己派生的计数行（**不手数**）：`反证格：14/14 有效；探针格 1 格（不计入有效数，它验的是「报什么」不是「拦不拦」）` + `全撤销后终态：rc=0` + `✅ 视觉门禁通过（定义 91 / 引用 91）`。

⇒ §12.10 未跑清单里的第 5 项（断言 4 三子句）**本批已收**；§12.2 台账行 ⑩ 的「10 格」自此成为历史值（现值 14 格 + 1 探针）。

### 13.3 探针格探到的东西：「读不到源就 fail」这句**只对一半成立**

这条不是设计批的宣称，是视觉件 §11 F8 里我自己写下的全称句。拿实测把它剖开：两个字典读取口形状不同 —— `LAMP_GROUPS` 走 `fail.push`，`EVENTS` / `LAMP_WHY` 走 `dictKeys` 里的 `throw new Error`。各来一格，实取：

| 口 | 变异 | rc | 失败清单（stdout） | 形状 |
|---|---|---|---|---|
| `LAMP_GROUPS`（fail 口） | 重命名为 `MUT_LAMP_GROUPS` | **1** | **有**，报「读不到 const LAMP_GROUPS」 | 可读的失败 ✅ |
| `EVENTS`（throw 口） | 重命名为 `MUT_EVENTS` | **1** | **stdout 全空**，无「视觉门禁失败」标记 | 栈：`check-tokens.mjs:165` → `if (!block) throw new Error(\`${where} 里找不到 const ${name}\`);` → `^` |

⇒ **两条结论**：

1. **rc=1 不足以区分「门禁拦住了」与「门禁自己崩了」** —— 两口 rc 完全相同，唯一可分的读数就是**有没有那段失败清单**。任何拿 `rc != 0` 当「门禁有效」的读法（包括本件以前一切只在 rc 上成立的陈述），在 throw 型口上会把「工具自己抱病」读成「产品违规」；反过来用 grep 找红字也会读成「没报红 ⇒ 通过」。这一型与本仓《ExitCode 误判》同族，不新。
2. **F8 那句全称句需收窄为实测支持的半句**：现在只证了 `LAMP_GROUPS` 一口 fail；`dictKeys`（事件字典与灯说明字典）与 `healthFields`（两层 `HealthResponse` class 头）三处**仍走 throw**。⇒ 已在视觉件 §11 F8 行就地订正射程，并列入在册缺口（下面 §13.5）。

**本批没去修那三口**（修 = 把 `throw` 换成 `fail.push` + 返回空集，两行改动，属门禁自己的代码，不碰后端也不改判据）。不修的理由不是「不想」，是**口径纪律**：这批的授权射程是「把已登记的欠项做完」，把一条刚探到的缺口当场改成产品行为属开新方向 —— 交用户拍板。

### 13.4 本批复跑命令（逐字可复跑，全部 2026-10-31 实取）

```bash
node .tmp-scratch/ap-visual/mutate-v1.mjs        # 14/14 有效 + 探针 1 格 + 终态 rc=0
node web/scripts/check-tokens.mjs                 # rc=0（定义 91 / 引用 91）
node .tmp-scratch/ap-visual/probe-throw.mjs       # §13.3 那两段 stderr 原文的取法（finally 必撤销）
```

全仓门禁（八道 + 上述两道）的第六批终值在 **§13.6**。

### 13.5 未覆盖清单更新（§12.10 的随动）

- **已收**：第 5 项（断言 4 三子句未证有牙）⇒ 见 §13.2。
- **新增一项在册缺口**：**三口 throw 未收 fail**（`EVENTS` / `LAMP_WHY` / 两层 `HealthResponse` class 头）。本批只登记与取证，未改门禁；收它属 PR-0 一并处置还是单独小批，**待拍板**。
- **其余五项原样不动**：V4 实拍（阻塞）/ 窄档无横向滚动判据（未取）/ 真库与真 SSE 流（射程外）/ `make ci-web`（目标未建）/ CJK 回落脚本观感（未实测）。

### 13.6 第六批全量门禁终值（文档回写后复跑）

> 本表在四份文档随动回写**之后**取，取完不再改文档 —— 改了就得重取。
>
> ⚠ **本表自第七批起是历史快照**（指针本批补）：第七批又改了四份入库文档 + `web/README.md`，本表那些行里有几行不再是现值（尤其与文本量相关的几道）。**现值在 §14.7**；引本表时引的是「第六批收尾时是什么样」，不是「现在是什么样」。

实取时刻 **2026-10-31**（本轮终跑，命令逐字同 §13.4 与取证件 §12.12；`powershell -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/gates4.ps1`）：

| # | 门禁 | 第五批终值（§12.12） | **第六批终值** | 差值定性 |
|---|---|---|---|---|
| ① | HEAD / 分支 | `d140f91f` / `feat/nl2sql-ttl-and-006-slim` | **同值** | 本批零提交、零建分支 |
| ② G1 | 后端目录对 `d140f91f` 的 diff | **0 行** | **0 行** | 红线：本批未碰一个后端字节 |
| ③ G2 | `git status` 非 docs 条目 | 7 条（全在 `web/`） | **7 条，逐字同集** | 本批只改了 `web/README.md`（已在集内），**没新增一个文件** |
| ④ G3 | `Test-Path web` | True | **True** | 不变 |
| ⑤ G4 | `check_doc_sync.py` | rc=**0**（0 警告） | **rc=0（“文档同步校验通过（0 警告）”）** | 不变；⚠ 口径同 §12.12：它根本不扫本批四份文档 |
| ⑥ G5 | `ruff check .` | rc=**0** | **rc=0（All checks passed!）** | 不变（本批仍未动 `.py`；两个取证脚本住 gitignored，这道不扫） |
| ⑦ G6 | 就地引用边自查 | total=**139** / unique=**69** / unresolved=**5** | **139 / 69 / 5 逐字不动**，BAD 五条同旧集（docs/adr/0003、0012、0013、那条故意的 …-10-30.mX 夹具、docs/plans/README.md）| 本批往四份文档里加了四张表与两个新小节，**新增 0 条 docs 引用边** —— 又是做出来的（指代一律中文 + 不拿反引包路径）。⚠ **本行本身就踩了一次**：本节初版把那五条 BAD 路径中的两条写进了反引号，下一轮复跑 total 从 139 跳到 **141**（unique/unresolved 不动，因为那两条已在集合内）—— 与 §12.12 那条「G6 被自己 +4 条边」完全同族，**同一型错误在同一条款里第三次出现**。改回普通文本后复跑回到 **139** |
| ⑧ G7 | 提及数 | 8 / 9 / 11 | **8 / 9 / 11** | 三值不动且**这次连构成也未动**（同上口径：写文档时刻意不重复文件名） |
| ⑨ G8 | 表格完整性 | 四份全 **0** | **四份全 0** | ⚠ **本批这一道真的拦住了东西**：改写反证表时一度掉行首竖线（一度塌成散文）、一度掉行尾竖线（一度破表），两次都被这一道拦住，已逐行补齐 |
| ⑩ | `node web/scripts/check-tokens.mjs` | rc=**0**：定义 **91** / 引用 **91**；事件 **12** / 字段 **30**；断言 6 三行 **12/12、30/30、30/30** | **逐字同值（rc=0）** | 本批**未动一条断言与一个样式值** ⇒ 这四个读数应当不动，动了就是改错东西 |
| ⑪ | `node .tmp-scratch/ap-visual/mutate-v1.mjs` | 10 格全有效 + 终态 rc=**0** | **反证格 14/14 有效 + 探针 1 格**（计数行由脚本从 rows 派生，不手数）+ 全撤销终态 rc=**0** + 末行 `✅ 视觉门禁通过（定义 91 / 引用 91）` | 新增五格的逐格读数在 §13.2，探针那两行在 §13.3 |

⚠ **本节自己也被自己的行数推了一轮（与 G6 那两次同族）**：§8.1 新那张体量表刚写下时算的是「刀③ = 1614 行」（当时取证件 1109 / 工单件 diff 65），回抄本节终值时重取得取证件 **1127** / 工单件 diff **78** ⇒ 刀③ **1645**；而工单件随后又加了两句登记 ⇒ 现值再涨。**涨的全部就是登记这三个数的那几行本身**。⇒ 三处下游（工单件 §8.1 / 工单件 §13.4 第六批那行 / 本索引工程件那行）已统一改成**量级口径**（「刀③ 1600+ 行，含登记本行自身文字，引用前重取」），不再当可逐字复跑的常量引。这一型不靠删数字规避（删了就退回「拿没取过的数当约束」那个老坑），靠的是把口径从「精确值」改成「量级 + 重取口令」；刀① **825** / 刀② **644** 不受影响（样式三件、两个宿主页、门禁脚本本批一行未动，那两刀是硬值）。

⚠ **本段末句「刀① / 刀② 是硬值」自第七批起只对刀② 成立**：刀① 的构成里含 `web/README.md`，而它在第七批从 **118 涨到 142** ⇒ 刀① 现值 **849** 而不是 825。本段原句**不追改**（它是第六批收尾时的快照，追改就拿历史形状冒充现值了）；订正本体见 **§14.6** 末与工单件 **§8.1**。真正一行未动的只有样式三件与两个宿主页（第七批复取逐字同值：217 / 299 / 191 / 267 / 180）。

⇒ **本批全部八道 + 两道样式层门禁逐道实取，无一项靠推定**。未跑清单见 §13.5（五项原样 + 一项已收 + 一项新增在册缺口）。

## 14. 次日第七批（2026-10-31）：逐条收口在册欠项 —— 三口逐口实取、实拍通道成立、两处读数自我证伪

> 本批授权射程仍是「把已显式登记的欠项做完」：**零产品代码、零样式值改动、零 git 动作**；四份入库文档只动随动文字与表形，**一条判据原文没改**。凡需要拍板的（三口 throw 的处置、一屏读完 A/B/C、三刀体量、分支模型 (a)/(b)）一律**给证据不给结论**，逐项状态集中在 §14.8。

### 14.1 开工坐标与分支模型读数复跑（§12.11 那八行的现值）

实取时刻 **2026-10-31 09:32:22**（`Get-Date` 现取）。命令逐字同 §12.11，本表只写复跑值与定性：

| 项 | 命令 | 第五批（§12.11） | 第七批复跑 | 定性 |
|---|---|---|---|---|
| 远端清单 | `git remote -v` | 2 个 | **逐字同**：`company` 内网 SSH（fetch/push 俱在）+ `github-legacy`（push URL = `DISABLED-no-push` 禁推），**无 `origin`** | 不变 |
| `company` 远端分支 | `git ls-remote --heads company` | rc=**0**、1 条 `refs/heads/main` @ `fe22794c` | **rc=128**：`ssh: connect to host … port 30001: Connection timed out` + `fatal: Could not read from remote repository.` | ⚠ **本批未达（环境阻塞）**。网络失败**不等于远端形态变了**，也不得据此改口；复取需在内网可达的机器上跑同一条命令 |
| 本地分支全表 | `git for-each-ref --format=… refs/heads` | 8 条，3 条 upstream 指 `github-legacy` | **8 条同集**：`company-snapshot` fe22794c / docs/dependabot-round4-2026-10-24 ba01872c(legacy) / `feat/nl2sql-ttl-and-006-slim` d140f91f(无 upstream) / `fix/dependabot-pillow-13-2026-10-24` 1b2119e4(legacy) / `fix/dependabot-security-int` 43f86c68 / `fix/dependabot-security-oct-2026-10-24` f8f6b0cb(legacy) / `main` 88515cab(legacy) / `mirror/nl2sql-ttl-and-006-slim` 2011fe6a | 不变 |
| 本地 `main` 跟的是谁 | `git rev-parse --short main` | `88515cab` | **`88515cab`** | 不变 ⇒「不得当内网切点」原样有效 |
| 工作线与 `company/main` 同源否 | `git merge-base HEAD fe22794c` | rc=1、空 | **rc=1、空输出** | 不变；⚠ 这条**不需要网络**（`fe22794c` 在本地是 `company-snapshot` 的 tip）⇒ 上面那行网络失败不动摇「异宗历史」这条结论 |
| 互相领先 | `git rev-list --left-right --count main...HEAD` | 6 / 367 | **6 / 367** | 不变（本批零提交）。⚠ 这类数随工作线增长而漂，**引用前重取** |
| 当前分支 / tip / upstream | `git branch --show-current` + `git rev-parse --short HEAD` | `feat/nl2sql-ttl-and-006-slim` @ `d140f91f`，无 upstream | **逐字同** | 不变 |
| 本批账面归属 | `git status --short --untracked-files=all` | 11 条（docs 4 + `web/` 7） | **11 条**，逐条同名（两条 ` M`：顶层索引、工单件；两条 `??`：本件、视觉件；`web/` 七条 README / poc / poc-health / check-tokens / base.css / events.css / tokens.css） | 本批**没新增一个入库文件** ⇒「零 `git add`」可核 |

⇒ §12.11 那三条硬结论原样有效（唯一集成分支**无对象** / 切点**绝不取本地 `main`** / 账面越久越难拆成小 PR），但**第一条的本批复核只做到一半**：远端分支数这一格卡在网络上，属**环境未达**而不是已过。(a) 先在本地分支提交、不合不回 / (b) 新建内网集成分支并首推 `company`（D2）⇒ **仍待用户拍板，本批一条 git 动作也没做**。

### 14.2 三口 throw 的逐口实取（镜像树探针，后端目录 diff 仍 0 行）

§13.3 那张表只有两口有读数（`LAMP_GROUPS` 与 `EVENTS`），`LAMP_WHY` 与两层 `HealthResponse` 是**读代码推定** —— 而「台账写三口、只一口有读数」下一批就会当三口都实测过。本批补成逐口实测。

**为什么不能就地改**：`healthFields` 的变异目标是 `packages/shared-schemas/shared_schemas/health.py` 与 `applications/agent_server/schemas.py`，就地改再撤销 = 往产品源文件落一次写，撤销失败就是红线事故。⇒ 走**镜像树**：把门禁脚本 + 它读的 10 个文件（六个前端/样式 + 四个后端契约）复制进 gitignored 的 probe-tree 目录，**只在副本上变异**；**基线自证 = 未变异时必须 rc=0**（不成立就说明副本不忠实，下面所有读数作废）；`finally` 撤销 + 删镜像 + 打印 existsSync。

复跑命令 `node .tmp-scratch/ap-visual/probe-throw2.mjs`，本轮（2026-10-31 09:41）**stdout 原样实抄**：

```
镜像树基线：rc=0  stdout含「视觉门禁失败」=false
  stdout 末行：✅ 视觉门禁通过（定义 91 / 引用 91）

| 读取口 | 变异后 rc | 失败段 | stderr 栈 | 撤销后 |
| LAMP_WHY（dictKeys 第二口） | rc=1 | stdout 全空（throw 口） | 栈点 :165 · Error: poc-health.html 里找不到 const LAMP_WHY | 撤销后 rc=0 |
| healthFields 第一层 class 头 | rc=1 | stdout 全空（throw 口） | 栈点 :138 · Error: packages/shared-schemas/shared_schemas/health.py 里找不到 class HealthResponse | 撤销后 rc=0 |
| healthFields 第二层 class 头 | rc=1 | stdout 全空（throw 口） | 栈点 :138 · Error: applications/agent_server/schemas.py 里找不到 class HealthResponse | 撤销后 rc=0 |
| LAMP_GROUPS（fail 口·正对照） | rc=1 | 有失败段（fail 口） | 栈点 : ·  | 撤销后 rc=0 |

镜像树已删除：existsSync=false（必须 False）
```

紧接同一轮的**红线复核**：`git diff --numstat d140f91f -- applications packages scripts Makefile .github/workflows Dockerfile .dockerignore` = **空输出、lines=0**；`Test-Path .tmp-scratch/ap-visual/probe-tree` = **False**。

⇒ 四条结论：

1. 四口（`EVENTS` 见 §13.3 + 上面三口）**全部实测为 throw**，一口（`LAMP_GROUPS`）为 fail ⇒ 全称句「读不到源就 fail」的射程**只有那一个口**；视觉件 §6 探针行与 §11 F8 行已按逐口读数改写。
2. **正对照有效**：同一镜像树、同一次运行里 fail 口报出可读失败段、throw 口 stdout 全空 ⇒ 「stdout 有没有那段」不是探针读不出来的假象，是两口形状真的不同。
3. 四口 rc 同为 **1** ⇒ **任何仅在 rc 上成立的门禁陈述都不区分「拦住了」与「工具自己崩了」**（§13.3 第 1 条从两口扩到四口，本仓所有此类陈述仍降一级）。
4. **仍未修**：把 `throw` 换成 `fail.push` + 返回空集是门禁自己的代码（两行），不在本批射程内 ⇒ 待拍板，选项与代价集中在 §14.8。

### 14.3 V4 实拍：通道成立 + 逐张形状读数 + 两条 dark 通道的**隔离对照**

命令 `node .tmp-scratch/ap-visual/shot-v4.mjs`（headless Chrome + CDP，**零依赖**；实取 2026-10-31 09:08:43–09:08:51），**14 张 PNG** 落 gitignored 的 shots 目录。⚠ 它**不是**判据原文绑的那条通道（判据绑 `pnpm dev`/`preview`，本机未装 pnpm、PR-0 未开工），所以本节的读数支持「形状与通道成立」，不支持「V4 已过」。

对话页 poc.html（`lampDomInTalkPage` **三档全 false** ⇒ 灯阵确实不在对话页，PR-2 那条形态订正有图证；`evRows=13` = 12 类 + 1 条未识别事件行）：

| 档位 | light sha | dark sha | docScrollHeight | gridCols | 列宽 | hScroll |
|---|---|---|---|---|---|---|
| 1280×900 | `5e8f3d95ca57` | `0feb84979f54` | 1003 | 2 | 515.67 / 656.31 | false |
| 768×1024 | `cf541444b2ec` | `953220c40989` | 1228 | 2 | 318.55 / 405.45 | false |
| 375×667 | `ecb0e3e9c518` | `764e7f483eb1` | 927 | 1 | 351 | false |

灯页 poc-health.html（`lampCount=30`、`whyNodes=30`、`lampNameBreak` **三档全 0** ⇒ 灯名无断行）：

| 档位 | light sha | dark sha | docScrollHeight | lampCols | 卡宽 | 网格宽 | lampsAboveFold | oneScreenFits |
|---|---|---|---|---|---|---|---|---|
| 1280×900 | `bfb72e4a72cc` | `24d72824f93d` | 1410 | 4 | 283.5 | 1158 | **18** | false |
| 768×1024 | `a4d994b19f75` | `1ab01f31be7e` | 2085 | 2 | 351 | 710 | 12 | false |
| 375×667 | `b9e6cdd1d4b4` | `6ade0900b1ff` | 3550 | 1 | 325 | 325 | 1 | false |

外加两张 auto+媒体dark 副本（1280×900）：`v4-poc-autoMediaDark-1280x900.png` = `0feb84979f54`、`v4-poc-health-autoMediaDark-1280x900.png` = `753f3a821e51`。

**两条子判据的读数形状**：
- **窄档无横向滚动**：`hScroll=false` **14 张全 false**；且逐张 `docScrollWidth == docClientWidth == innerW`（1280 / 768 / 375），`bodyScrollWidth` 同值，`overflowSample` **全空数组** ⇒ 这条从推定变成逐张读数。取法关键 = 在 `Page.navigate` **之前**就 `Emulation.setDeviceMetricsOverride`，首帧即目标宽度 ⇒ §11 F6 那一型（跳帧读到旧布局遗留）在这条通道上结构性不可能发生（这正是本批换通道的原因，不是口味）。
- **四档形状可辨**：`lampCount 30 / whyNodes 30` 逐张成立，加上下面那次真图判读。
- **页面异常 0 条**：`Runtime.exceptionThrown` 累计 **0**（脚本末尾打印）。

**两条 dark 通道是否等价**（本批唯一需要新写方法的一条）：上一支探针 `probe-dark-font.mjs`（09:13）在灯页比 A（媒体dark + auto）与 B（点按钮 dark），235 条逐元素指纹**差 2 条**，全在 `BUTTON.btn` 的 `backgroundColor` 且两值**对调**；令牌归属用 `Select-String` 现取：`tokens.css` 114/162 行 `--n-050: #1c2128`、133/181 行 `--blue-tint: #1f2b3d` ⇒ `rgb(28,33,40)` / `rgb(31,43,61)` 分别是这两枚 ⇒ 差异是**哪颗按钮处于选中态**，不是令牌解析分叉。

本批把混淆变量钉死后又跑一支 `node .tmp-scratch/ap-visual/probe-dark-health.mjs`（09:44）：X = `data-theme="dark"`（媒体 light）、Y = 无 `data-theme` + 媒体 dark，且两态 `aria-pressed` 强制一致（都 `dark=true`），实抄：

```
{"state":"X","themeAttr":"dark","ariaPressed":"auto=false,light=false,dark=true","pngSha":"ec8c14e826af","fpCount":235,"psCount":0,"fpSha":"6f7ad06ac2f4"}
{"state":"Y","themeAttr":"(auto)","ariaPressed":"auto=false,light=false,dark=true","ariaPressedAtLoad":"auto=false,light=false,dark=true","pngSha":"ec8c14e826af","fpCount":235,"psCount":0,"fpSha":"6f7ad06ac2f4"}
逐元素指纹 X vs Y：条数 235/235，差异条数 0
伪元素指纹 X vs Y：条数 0/0，差异条数 0
```

⇒ **选中态一致时两条通道逐字节相同（同一 pngSha）且 235 节点指纹差 0** ⇒ 「`[data-theme=dark]` 块与媒体查询块解析分叉」这个假设被**正面否证**，断言 5 只比两块声明的射程**没有洞**。两个副产物：① `psCount=0` 顺带证伪「四档状态点是伪元素画的」——它们住在真实节点上，所以逐元素指纹覆盖得到；② 本轮 X 的 sha 与上一支探针 B 的 sha 逐字相同（`ec8c14e826af`）⇒ 这条通道**跨两轮独立运行可复现**。

⚠ **一条未闭合的读数异常（登记，不掩盖）**：shot-v4 那 14 张里 poc.html 的两通道**sha 相同**而 poc-health.html 的**不同**。本批用干净 profile 复跑对话页（`node .tmp-scratch/ap-visual/probe-dark-poc.mjs`，09:43）实取两态**不等**：

```
{"state":"A-媒体dark-auto","themeAttr":"(auto)","ariaPressed":"auto=true,light=false,dark=false","pngSha":"2c6ebbab968a","fpCount":195,"fpSha":"290e53b34b68"}
{"state":"B-点按钮dark","themeAttr":"dark","ariaPressed":"auto=false,light=false,dark=true","pngSha":"eff9bcd1f620","fpCount":195,"fpSha":"47949492f261"}
poc.html A vs B 指纹条数 195/195，差异条数 2   （[9]/[11] BUTTON.btn 的 --blue-tint ↔ --n-050 对调）
```

机制定位：两页都在加载时执行 `applyTheme(localStorage.getItem(THEME_KEY) || 'auto')`（对话页 263 行、灯页 177 行）⇒ **前一次点击会经 storage 跨导航携带，把 auto 态的选中态洗成 dark 态**，而 shot-v4 的 `goto` 只在导航**之后**抹 `localStorage` 与 `data-theme`（抹得掉属性，抹不掉已经点亮的 `aria-pressed`）⇒ 那两张 auto 副本**不是干净的通道对照**。⇒ 处置：**「两条通道等价」的证据改用上面那支隔离探针，不引 shot-v4 的 sha 相等**（它与自己那对灯页读数还互相矛盾）；灯页那一对在选中态被洗成相同之后**为何仍差**，本批**未定性**（剩下的候选是截图时刻的其他瞬时量）。它不动 V4 的两条子判据 —— 那两条用的是逐张形状读数，不是通道对照。**这一型值得记的**：拿同一轮里前后相承的读数当**独立**证据，等于用一个数的两次出现冒充两次取证。

**真图判读**（本批用读图方式看了 4 张：poc light/dark 1280、poc-health dark 375、poc-health dark 1280）：四档状态形状可辨（实心绿圆 / 空心圆 / 实心橙点 / 空心方块）、375 档单列且右侧无内容被切、dark 那张「深色」按钮的底 tint 与另两颗不同（正是指纹那 2 条）。**观感判读属人** ⇒ 这是 V4 未过的第三条理由，不是第一条。

⇒ **V4 现值**：实拍通道已成立（上一版那句「本机阻塞」只否掉了 IDE 浏览器面板那一条通道）、14 张已取、两条子判据达成；**本道仍未过**：① 跑在静态宿主页 + 零依赖 Node 服务器上而判据绑 pnpm 通道；② 判据原文「6 张」与实物不同步（拆页后应为两页 × 三断点 × 两主题 = 12 张起），**本批未改判据原文**；③ 观感待人判。视觉件 §7 V4 行按这三条改写。

### 14.4 字体：先证伪自己用的那个 API，再取实际落地的平台字体

在册那句「屏上是系统回落、不是 Plex」原先只是**断言**。shot-v4 里顺手取的 `document.fonts.check('16px "IBM Plex Sans"')` 返回 **true**（14 张全 true），看着像反证。本批没拿它当反证，**先验这个 API 本身**（`probe-dark-font.mjs` 09:13 实抄）：

```
{"check_plex":true,"check_bogus_control":true,"check_yahei":true,"loadedFaces":0,
 "bodyFontDecl":"\"IBM Plex Sans\", \"Noto Sans CJK SC\", \"Microsoft YaHei\", system-ui, sans-serif"}
```

对一个编出来的不存在字体名它也返回 **true**（控制组），且 `document.fonts.size = 0` ⇒ **该 API 在没有任何 `@font-face` 的页面上没有判别力**，那条 true 不是反证。换 CDP `CSS.getPlatformFontsForNode` 逐节点取（`node .tmp-scratch/ap-visual/probe-font2.mjs`，09:15 实抄）：

```
poc.html：扫描节点 234，栅格化出文字 99
  Microsoft YaHei|isCustomFont=false|MicrosoftYaHei 921 / Cascadia Mono 384 / YaHei-Bold 130 / NSimSun 14 / CascadiaMonoRoman-SemiBold 6 / Noto Sans SC 4
poc-health.html：扫描节点 245，栅格化出文字 193
  Cascadia Mono 1180 / Microsoft YaHei 1094 / YaHei-Bold 160 / NSimSun 18 / Noto Sans SC 2
```

⇒ 两页 479 个节点里栅格化出文字的 292 个**全部 `isCustomFont=false`**，实际落地只有 Microsoft YaHei / Cascadia Mono / NSimSun / Noto Sans SC 四个族，**Plex 一次未出现** ⇒ 在册那句从断言升为**实证**（`web/README.md` 那句「字体未启用、系统回落」现在有据）。副产物订正：上一版把回落面写成「Segoe UI + 微软雅黑」，**实取里没有 Segoe UI**，已按实取改。

**CJK 回落脚本下的行盒**（§12.10 未跑清单第 6 项的「行盒」那半句，同一次 shot-v4 运行尾部）：`{"cjk":{"cjkHeight":20.39,"lineHeightPx":"20.4px","font":"\"IBM Plex Sans\"","latinHeight":20.39}}` ⇒ 同一 `.lamp__why` class 下中英混排行与拉丁行**行盒同高（20.39）**，`--lh-*` 令牌生效；「观感」那半句交给上面那次真图判读，仍属人判。

### 14.5 「一屏读完 30 盏」：三个选项的代价在真实视口逐档量化

同一次 shot-v4 运行尾部的 what-if（**只在内存里删 DOM / 改内联 grid，未动一个样式文件**；`goto` 在每个 what-if 前重跑，基线态与实验态不互相污染）。2026-10-31 实抄四档：

| 档位 | 基线 scrollHeight / 列数 / 卡宽 | B = 砍掉每张卡的说明段 | C = 地板 260px→180px | 三选项 fits |
|---|---|---|---|---|
| 1440×900 | **1410** / 4 / 323.5 | 1191 / 4 列 | 1206 / **7 列**（181.42、181.44） | base false · B false · C false |
| 1280×900 | **1410** / 4 / 283.5 | 1191 / 4 列 | 1322 / 6 列（186.33） | 三 false |
| 768×1024 | **2085** / 2 / 351 | 1695 / 2 列 | 1725 / 3 列（231.33） | 三 false |
| 375×667 | **3550** / 1 / 325 | 2819 / 1 列 | 3550 / 1 列（**未变**） | 三 false |

配套两把尺：① **首屏实际可见 18/30 盏**（1280×900，`lampsAboveFold=18`；768 档 12、375 档 1）；② 5 列的物理门槛 —— 本批另跑一支 `node .tmp-scratch/ap-visual/probe-gridwidth.mjs`（09:47）在真实视口直读：`1440×900 → gridClientWidth=1318, cols=4, cardWidth=323.5, gap=8px, fiveColNeed=1332`；`1280×900 → gridClientWidth=1158, cols=4, cardWidth=283.5, fiveColNeed=1332`。

⚠ **这一支推翻了自己在册的那把 razor-edge**：上一版写「5 列需 `5 × 260 + 4 × 8 = 1332px`，而容器实宽 **1328.80px** ⇒ 只差 **3.2px**」（第五批 iframe 通道取的）。真实视口下网格内容宽是 **1318** ⇒ 差 **14px**，不是 3.2px。**两个数都留着**（1328.80 是 iframe 通道的旧读数，正是 §11 F6 那一型的现场：同一台机器、同一个宽度，换通道就差 10.8px），但**下游一律改引 1318 / 14px**，`web/README.md` 已随动改正。

⇒ **结论改变了拍板的性质**：B 与 C **在任何真实档位都不能把 30 盏送进一屏**（最好的 1440×900 下 B=1191、C=1206 均 > 900；375 档下 C 完全未变）。所以拍板不再是「选哪个能让它成立」，而是「**只剩 A（改措辞）与现实一致**，B/C 作为『让它成立』的选项已被实测证伪」。**本批未改判据原文**，三个选项仍待人回答（A 的具体改法已在视觉件 §11 F1 行给出候选措辞）。

### 14.6 本批的方法结论与自犯订正（六条，全部当场可复跑）

1. **发往产品源文件的变异一律走镜像树**。一个可复用的形状：固定一份「门禁脚本 + 它读的全部文件」清单（本例 10 个）、建镜像前先 `rmSync` 强制洁净、**基线必须 rc=0**（否则报红原因就错了，读数全废）、逐口变异后紧接 `refresh` 从真源重建、`finally` 再重建 + 删镜像 + 打印 existsSync、**脚本末尾自带一道路径守卫**（`if (!MIRROR.includes('probe-tree')) throw`）防止误把真仓当镜像。另存一份可复跑读数：本轮基线 rc=0 + 四口全 rc=1 + 末行 existsSync=false + 同一轮的后端 diff = 0 行。
2. **通道形状决定读数可信度**。在 `Page.navigate` **之前**就设好真实视口 ⇒ 首帧即目标宽度，F6 那一型结构性不可能发生。本批拿这条重取了两个旧读数，**两个都漂了**：`scrollHeight` 1406（iframe）→ **1410**（真实视口）、网格内容宽 1328.80 → **1318**。⇒ 一个可复用的口径：**凡几何读数，注明通道**；同一机器同一宽度换通道就能漂 4–10px，这不是页面缺陷而是量测工具的差。
3. **验一个 API 能不能用，先拿控制组验**。`document.fonts.check` 对编出来的字体名也报 true ⇒ “它报 true”不构成任何反证。这一条不只适用于字体：任何“工具报了一个正常值”的读数，都该先问“它对错误输入报不报”。
4. **拿同一轮里前后相承的读数当独立证据 = 用一个数的两次出现冒充两次取证**（本批新踩，已写进 §14.3）。机制很具体：两页都在 load 时读 storage，而 harness 只在导航**后**抹属性 ⇒ 上一个态的 `aria-pressed` 活到了下一个态里。可复用的修法：**要么每态清一次 storage（导航前），要么把混淆变量显式打印出来再比**（本批采后者，所以能拿到差 0 条的硬读数）。
5. **PowerShell 5.1 的两个自坑**（都是命令错，不是文件错）：A) `powershell -Command "try { Invoke-WebRequest … }"` 这层嵌套引号会被拆坏，PS 反过来去解析一个 HTML 文件的内容，报一串 `The '<' operator is reserved for future use` ⇒ 探服务存活改用 `node -e "fetch(…)"`。B) `Select-String -SimpleMatch` 配正则交替（`a|b`）**永远 0 命中**（SimpleMatch 下竖线是字面量）⇒ 去掉该开关后同一命令命中 4 行。**0 命中不等于不存在**，这句话对命令错也成立。
6. **Node 24 的一个语法坑有最小复现**（同目录 t1/t2/t3.mjs，本批**重跑确认仍然成立**）：`await ev(多行模板)` **直接写进对象字面量属性**时，`node t1.mjs` 报 `SyntaxError: missing ) after argument list`；先赋值再引用（t2）或属性内写单行模板（t3）各自 rc=0。**坑在两者叠加，不在任一半**。运行时：`node -v` = **v24.12.0**。

**本批自己引入并当场订正的五处（逐条可查）**：

| # | 本批犯的 | 当场怎么收的 |
|---|---|---|
| 1 | 在顶层索引里先写了「本批**真的踩了一次**（引用边）」—— **写时还没取数** | 随后 gates 实跑 total 仍 139 ⇒ 当场改口为「新增 0 条引用边，没踩进去」。**登记这一型：拿没跑过的数写「我踩了坑」与拿没跑过的数写「我过了」是同一种错** |
| 2 | 改写视觉件 §7 V4 行时**挤掉了它原有的 F7 交叉指针** | 补回，并写明「那一格本批在真图上重判为成立，但 F7 本身的结论不因此回退」 |
| 3 | 自造了一句指向**已被本批替换掉的那一行**的指针（“上一行那句……”） | 改为指向仍然存在的 §8 表内行。⇒ 「先改后指」必带一轮“指的东西还在吗”的自查 |
| 4 | 两处中文错字（“第六批**木**身”、“不得读成**木机**拍不出”） | 已改；本批收尾另跑一次全库错字复扫（见 §14.7 附行） |
| 5 | 视觉件 §8 随动表**缺第六批整行**（在册随动缺口， grep 证到只写到第五批） | 本批补写，并在行内明标「本行是第七批补写的，不是当时写的」。口径：**不拿「反正 §11 里有」当免登记理由** |

另加两笔本批新登记的**读数级订正**（不是错字，是错数）：① `web/README.md` 与视觉件两处写的「Segoe UI + 微软雅黑」里 **Segoe UI 实取未出现**（见 §14.4），已按实取改；② razor-edge「只差 3.2px」已被真实视口重取推翻为 **14px**（见 §14.5），三处下游同步改了，旧数保留并注明不得当现值引。

### 14.7 第七批全量门禁终值（文档回写后复跑）

> 本表在四份入库文档 + `web/README.md` 全部随动回写**之后**取。**与 §13.6 同族的自指仍未消除**：本节自己（§14.7 + §14.8）就是写在本表之后的文字，它一落笔取证件的物理行就涨 ⇒ 凡与文本量相关的读数（刀③ 体量、本件行数）按**量级 + 引用前重取**读，不当可逐字复跑的常量。

实取时刻 **2026-10-31 10:05–10:12**（终跑）。命令逐字：`powershell -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/gates4.ps1`、`node web/scripts/check-tokens.mjs`、`node .tmp-scratch/ap-visual/mutate-v1.mjs`、`powershell -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/typo-scan.ps1`。

| 门禁（含编号） | 第六批终值（§13.6） | **第七批终值（实抄）** | 差值定性 |
|---|---|---|---|
| ① G0 HEAD / 分支 | `d140f91f` / `feat/nl2sql-ttl-and-006-slim` | **逐字同值** | 本批零提交、零建分支、零 `git add` |
| ② G1 后端目录对 `d140f91f` 的 diff | **0 行** | **lines=0**（命令：`git diff --name-only d140f91f -- applications packages scripts tests eval deploy Makefile pyproject.toml`） | 红线：本批未碰一个后端字节（镜像树探针用后即删，existsSync=false 同轮取） |
| ③ G2 `git status` 非 docs 条目 | 7 条（全在 `web/`） | **lines=7，逐字同集**（README / poc / poc-health / check-tokens / base.css / events.css / tokens.css） | 本批只改了已在集内的 `web/README.md`，**没新增一个入库文件** |
| ④ G3 `Test-Path web` | True | **True** | 不变 |
| ⑤ G4 `check_doc_sync.py` | rc=**0** | **rc=0**· stdout：`✅ 文档同步校验通过（0 警告）` | 不变；⚠ 口径同 §12.12 / §13.6：它根本不扫本批这几份文档里的路径引用，它的绿不能当「互指已证」 |
| ⑥ G5 `ruff check .` | rc=**0** | **rc=0**· stdout：`All checks passed!` | 不变（本批仍未动 `.py`；取证脚本住 gitignored，这道不扫） |
| ⑦ G6 就地引用边自查 | total=**139** / unique=**69** / unresolved=**5** | **139 / 69 / 5**，BAD 五条同旧集 | ⚠ **本批真踩了一次，同族第四次**：首轮实取是 **140 / 70 / 6**，新增那条 BAD 是 **一条 git 分支名** docs/dependabot-round4-2026-10-24（本地分支全表里逐字抄来的 ref 名，被反引包住后正好命中 G6 的「docs/ 开头路径状」形状）。它不是一句文档引用⇒ 处置是**去掉那一层反引号**（不删读数、不改分支名、不动门禁正则），复跑回到 139 / 69 / 5。**这一型的新知识：G6 正则分不清「docs 开头的分支名」与「docs 路径」**，凡逐字抄 git 输出进台账，带 docs/ 前缀的 ref 一律不带反引号（本行就是这个口径的执行样本：该分支名在本表内全程裸写）。⚠ **第五轮又推了一次，但那一型不同**（真边重复计数，不造 BAD）：本表终值改读 **141 / 69 / 5**，成因与处置见下「第五轮」段 |
| ⑧ G7 提及数 | 8 / 9 / 11 | **8 / 9 / 11** | 三值不动且构成也未动（本批写随动时刻意不重复文件名） |
| ⑨ G8 表格完整性 | 四份全 **0** | **四份全 0** | ⚠ 但「行首行尾竖线齐」只拦塌成散文那一型，**拦不住列数不对**——本批新探针 T4 拦下两处真破表（见附行 B） |
| ⑩ `node web/scripts/check-tokens.mjs` | rc=**0**：定义 **91** / 引用 **91**；事件 **12** / 字段 **30**；断言 6 三行 **12/12、30/30、30/30** | **逐字同值（rc=0）** | 本批**未动一条断言与一个样式值** ⇒ 这四个读数应当不动，动了就是改错东西 |
| ⑪ `node .tmp-scratch/ap-visual/mutate-v1.mjs` | 反证格 14/14 有效 + 探针 1 格 + 终态 rc=**0** | **同形：反证格 14/14 有效 + 探针格 1 格**（计数行由脚本从 rows 派生，不手数）+ 全撤销终态 rc=**0** + 末行 `✅ 视觉门禁通过（定义 91 / 引用 91）` | 新增的三子句格与 fail 口探针格读数不变；throw 那格的失败段仍为空（符合预期）——逐口剖开的四口读数在 §14.2，不在本表 |

⇒ **十道逐道实取，无一项靠推定**；未跑项全部在 §14.8 里指名，没被隐去。

**第四轮终验（本表与 §14.8 全部写完、且工单件 §8.1/§13.4 与 `web/README.md` L136 这最后两组随动编辑落地之后再跑一遍）**，实取时刻 **2026-10-31 10:07–10:09**：G0 `d140f91f` / `feat/nl2sql-ttl-and-006-slim`；G1 **lines=0**；G2 **lines=7** 同集；G3 **True**；G4 **rc=0**·`✅ 文档同步校验通过（0 警告）`；G5 **rc=0**·`All checks passed!`；G6 **139 / 69 / 5**（BAD 五条同旧集）；G7 **8 / 9 / 11**；G8 四份 **全 0**；`check-tokens` **rc=0**（定义 **91** / 引用 **91**、事件 **12** / 字段 **30**、断言 6 三行 **12/12、30/30、30/30**）；`mutate-v1` **rc=0**（反证格 **14/14** 有效 + 探针 **1** 格 + 终态 `✅ 视觉门禁通过（定义 91 / 引用 91）`）；`typo-scan` **T1=2 / T2=18 / T3=0 / T4=0 / T5=0**（脚本提取 **15** 个标签）；`git diff --numstat d140f91f -- docs` = **8 2** `docs/README.md` + **86 8** 工单件 ⇒ 刀③ 构成未变；`git status --short --untracked-files=all` = **11 条**；`node -v` = **v24.12.0**。⇒ **最后两组编辑一格计数都没推动**（G6 / G7 / G8 / T2 / T4 / T5 全部与第三轮逐字同值）；本段写下之后又溢了一次，见下一段。

**第五轮（登记本段自己的编辑溢出的两个自犯：一个在计数里、一个在我刚写的那句归因里）**：把上一段写进本表后复跑，**G6 total 从 139 变 140**，unique **69 不变**、unresolved **5 不变**、BAD 五条同集；G7 / G8 / T1–T5 / 其余九道**逐字不变**。

新边定位（命令：`node .tmp-scratch/ap-visual/probe-g6edge.js`，它逐字套用 gates4.ps1 的 G6 三元表达式并打印行号）：本件内命中 15 次 / 11 个 unique / 5 条 BAD（与全库 140/69/5 不矛盾，前者是单文件子集），多出的那一条是 **`docs/README.md` 的第 4 次出现**（前三个在 **L597 / L622 / L625**，本件早已带反引）。

⚠ **本段的上一版把成因归到「命令串里的 docs 参数」和「该名字在本件从未被反引包住」——两句都是没实测就落笔，现已被上面这条探针证伪**（它本来就包住过三次）。这一型与台账反复点名的「因果句不跑就写」同族，只是这次跑的是自己的探针、溢的是自己上一段。**真正的机制更简单也更容易被忽略**：G6 的 **total 数的是出现次数不是 unique** ⇒ 同一个**合法目标**多写一次就 +1，而 unique 与 unresolved 不动。所以这一型与行 ⑦ 那一型不同层：分支名那次是**假边**（造出新的 BAD，必须去反引），这次是**真边重复计数**（目标存在，它推的只是 total）。**处置**：保留该反引（删它等于遮掉一条真实互指），不拆命令串；并将本轮终值 **141 / 69 / 5**（10:13 实取）登记在本表行 ⑦ 末句（行 ⑦ 里那个 139 是第三轮及以前的值，不追改，它是取证链）。另记两条口径：**新增一支只读探针（probe-g6edge.js）不推动 G6/G7，但推动附行 A 的支数**（附行 A 存在的理由就是这个，它自己也没逃掉）；体量行同步：本件行数因本段编辑继续上涨（命令：`(Get-Content <本件>).Count`，引用前重取），本行自己也在推动它。

**附行 A：本批新建的取证 harness（逐支 + 创建时刻，命令：`Get-ChildItem .tmp-scratch/ap-visual -File \| Sort-Object CreationTime`）**。⚠ 下游三件文档（工单件 §13.4 第七批射程行 / 顶层索引两处）**一律指向本行而不抄支数**，因为抄数会被本批自己后续新建的脚本推漂（本批就写过一次「四支」，当时确实四支，最终十一支）：

| 脚本 / 产物 | 创建时刻 | 用途 |
|---|---|---|
| probe-throw2.mjs | 09:01:47 | 镜像树四口变异 + 基线自证 + 路径守卫（§14.2） |
| shot-v4.mjs | 09:03:43 | 实拍 harness：14 张 PNG + 几何/异常/what-if/字体读数（§14.3） |
| shots.out.txt | 09:04:03 | 上一支的 stdout 落盘（取证原件，住 gitignored） |
| t1.mjs / t2.mjs / t3.mjs | 09:05:35 / 09:06:20 / 09:06:20 | Node 24 解析坑的最小三分复现（§14.6 第 6 条） |
| probe-dark-font.mjs | 09:10:13 | 两页双主题等价判据 + 平台字体扫（§14.3 / §14.4） |
| probe-font2.mjs | 09:14:30 | 控制组：验 `document.fonts.check` 本身有无判别力（§14.4） |
| probe-dark-poc.mjs | 09:35:01 | 干净 profile 下 poc.html 两态对照（§14.3 后半） |
| probe-dark-health.mjs | 09:37:30 | 混淆变量钉死后健页两态逐字节等价（§14.3） |
| probe-gridwidth.mjs | 09:40:17 | 真实视口直读网格宽（§14.5 razor-edge 订正） |
| typo-scan.ps1 | 10:06（本批收尾） | 全库错字 / 形状复扫，五道 T1–T5（附行 B） |
| probe-g6edge.js | 10:12（第五轮） | 定位 G6 那条新边的行号（逐字套用 gates4.ps1 的 G6 表达式，**只读**） |
| typo.out.txt / gates-r1.out.txt | 10:07 / 10:03 | 两道终跑的 stdout 原件落盘 |

另记一个**本批新自登的词汇型污染**（它不在 T1 词表里，靠人工读段发现，已当场补进词表）：我把「捅出来 / 溢出来」一路写成了「拓出」——**「拓」既不是这个词也不是「抄」的规范写法，共四处**（本件 L1319 / L1321 / L1325 / L1353，均已就地改为「溢」；工单件 L468 那个「git 拓扑」是正经词，不动）。这一型与台账点名的「工具标签错字爬进文档」同族，只是它爬进来的是**我自己的口癖用字**：词表型探针永远不会发现你没放进去的词，所以复扫得跟一个**读段动作**，不能只跟探针读数。⚠ **本段就是靠人工读段读出来的，T1 当时报的是 2 不是 6** —— 这就是附行 B 头句那句「词表型检查永远不可能完备」的现场证据。

**修本段时自己又犯了本批最严重的一次编辑失误（当场自登）**：为了插入上段，我把 original_text 选成了附行 A 结论句的**句头**（「⇒ 共 **12 支**」）而不是它的**全文**，替换后句头被吃掉、两段粘连；修连时又把同一句的后半重复粘了一遍。**这一型的代价不是丑，是丢内容 + 造赃**：句头被吃掉而其余部分看起来仍完整时，下游看不出来 ⇒ **纪律：插入/改写时 original_text 必须含定位锚的完整一句（到句末），不得只取前缀；改完必须读回那一段**（本轮就是读回才发现的）。下面那段就是被恢复后的原句。

⇒ 共 **12 支**（十一支可执行 + 三支落盘产物中的两支已单列），全部住 gitignored 的 `.tmp-scratch/ap-visual/`，**不入库也不计刀**（与 `mutate-v1.mjs` 同性质）。⚠ 本行上一版写 **11 支**，第五轮那支只读探针落地后现为 12 —— **这就是本行头句那句「抄数会被后续新建推漂」在本批内的第二次现场应验**（第一次是顶层索引那句「四支」）；下游件已改为指向本行不抄数，本行自己不得例外。

**附行 B：全库错字与形状复扫（新建 `typo-scan.ps1`，五道）**。这一道不是存量门禁，是本批为了回答「你写的这些字里有没有错」而现做的一次自检，所以**必须同时报它的射程与它的误报**：

| 探针 | 它校什么 | 实抄读数 | 命中定性 |
|---|---|---|---|
| T1 | 本会话历史**真踩过的**错字型词表（不是完备检查） | **hits=2** | 两条命中同一个词（木机）：**§14.6 自犯表第 4 行**与**本行所在那张表的下一列里引用了那同一句**——两处都是把错字本身引号里写下来作证据。**属自指命中，不是活错字**；词表不排除引用行是故意留的（排除就是拿正则形状凑绿） |
| T2 | 反引号内「路径状」字符串的存在性（扩展到 web/ packages/ applications/ scripts/） | **hits=18** | **18 条逐条分类，无一是本批新造的活错指**：G6 在册 BAD 四条（adr/0003、0012、0013、plans/README）× 两份文件 = **8 条**；PR-0 计划落点 **10 条**（工单件 §9 文件清单里「将来要建」的路径，故意尚不存在：web/package.json 两份文件各一次 · web/pnpm-lock.yaml · web/dist · web/node_modules · packages/ui/package.json · scripts/check-events.mjs · scripts/check-tokens.mjs · web/src/assets/fonts/ 及其中一份 OFL 许可件）。⚠ **中间一轮曾报 19**，多出的那条是本行自己把那个少写扩展名的名字包了反引号（现已改普通文本）。**真正要修的那 1 条已修**：§12.6 把 web/README 写漏了 .md（第五批留下的，本批探针拦下） |
| T3 | 行内反引号奇偶（未闭合就是形状错的前兆，跳代码围栏） | **hits=0** | 初版没跳围栏时报过一大批 —— 全是围栏行本身（三个反引号）。**这一型值得记：探针首跑的大命中先怀疑探针自己，不要先去改文档**；修完后本表一度又报 1 —— 是本行原先写了三个反引号来介定围栏本身（现已改普通文本） |
| T4 | 表格行列数与表头一致（只计未转义竖线，跳围栏） | **hits=0（修后）**；共拦下**三处真破表** | ⚠ **G8 拦不到这一型**（它只校行首行尾竖线齐，不校列数）。三处：① 工单件 §13.4 一行单元格里写了未转义的 `Get-Content … \| Measure-Object -Line`（**本批自己引入**）→ 改为转义形；② §12 一张旧表里「前端 \| 3」（**既存，非本批**）→ 改为转义形；③ **本表（§14.7 那张十道门禁表）表头写了五列而十一个数据行全是四列**（**本批自己引入，且是写完 §14.7 后由终跑溢出的**）→ 把表头改成四列（编号并入首列，**没删一个格、没改一个字的内容**）。三处均内容逐字不变 |
| T5 | 变异脚本格标签是否被文档抄走（§12.3 那型：错字从工具爬进文档） | 脚本提取 **15** 个标签，**hits=0** | 首轮报 **1**（「读不到事件字典（探 throw 口）」未被文档抄走），本表把它写出来后归零——**这一型值得反向记：探针的命中可以因为台账开始引用工具标签而消失，那不是质改，是账面形状变了**。另记：初版提取表达式写错（找 label: 而脚本数组项是单引号开头）时报 **0 个标签** —— 那就是 AGENTS.md 战役条款说的「引擎整条是空的却报出好分数」，已先修探针再取数 |

⇒ **终跑（本表写完后又跑一遍）逐字读数：T1=2 / T2=18 / T3=0 / T4=0 / T5=0**（脚本提取 15 个标签）。其中 T1 两条是**引用错形自身的自指命中**，其余全部定性。词表型检查永远不可能完备，这一段的价值不在「归零」而在**每条命中都有去处**。

**体量三刀的本表时刻现取**（`foreach … (Get-Content <文>).Count` + `git diff --numstat`，**末轮 2026-10-31 10:13:27 实取**；前几轮的读数在下行里作为取证链保留）：`tokens.css` **217** / `base.css` **299** / `events.css` **191** / `web/README.md` **142** ⇒ 刀① **849**（五件里只有 README 在涨）；`poc.html` **267** / `poc-health.html` **180** / `check-tokens.mjs` **197** ⇒ 刀② **644**（一行未动）；取证件 **1390** + 视觉件 **434** + 工单件 diff **94**（86 加 8）+ 顶层索引 diff **10**（8 加 2）⇒ 刀③ **1930**。⚠ **本行自己已经被改过三次：10:22 那轮写 1381 / 1919，第四轮写 1384 / 1922，本轮（末轮）写 1390 / 1930** —— 三个数都曾经是当时实测，没有一个应被遮掉，故全部保留。**下游不得引本行的具体数作硬约束，只读「1900+ 量级，引用前重取」**；重取命令就是头句那条。

**第六轮（本批最后一次复跑，10:14:16）**：gates4 全道 **与第五轮末尾逐字同值**（G6 141 / 69 / 5 不再漂），typo-scan T1=2 / T2=18 / T3=0 / T4=0 / T5=0（15 标签）同值，本件行数因上两段各增一行而为 **1396**（10:17:56 实取 ⇒ 刀③ **1936**，取证件 1396 + 视觉件 434 + 工单件 94 + 顶层索引 10；G6 仍 **141 / 69 / 5 不漂**，因这两段没写任何带反引的 docs 路径）。样式两道另跑：check-tokens **rc=0**（定义 91 / 引用 91、事件 12 / 字段 30、断言 6 三行 12/12・30/30・30/30），mutate-v1 **rc=0**（反证格 **14/14** 有效 + 探针 **1** 格 + 全撤销终态 rc=0 + 末行绿），分支 feat/nl2sql-ttl-and-006-slim 不变、status **11 条** 不变。⇒ **本段是收口陈述：它自己不写任何带反引的 docs 路径，故它不推 G6**（这就是上一段那条新口径的正向执行：要登记一个推漂的数，就用不推漂的形状去写）。

### 14.8 在册欠项逐项状态表（本批唯一一张收口清单）

> 两栏强度必须分开读：**文档已回写** = 这句话已落进各件正文（可 grep）；**已验收通过** = 它对应的判据已有可复跑读数且读数支持该判据。**写完不等于过了**——这两栏不同的行就是本批还不能画勾的行。

| # | 在册欠项（来源指针） | 本批处置 | 文档已回写 | 已验收通过 | 复跑命令 / 读数落点 |
|---|---|---|---|---|---|
| 1 | 本节旧名 §13.6 的 `TODO_136` 占位符 | 已回填为第六批终值 + 挂历史指针；第七批终值是本表前面的 §14.7 | ✅ | ✅（终值已取） | §13.6 首句的指针行 + §14.7 全表 |
| 2 | `dictKeys`（EVENTS / LAMP_WHY）与 `healthFields`（两层 class 头）**三口仍走 throw** | 逐口实测补齐（含正对照），**一行门禁代码未改** | ✅ | ✅（形状已实测）；**但「该不该改 fail」不是本批能验的** | §14.2（逐口 rc / stdout / stderr 栈 / verbatim Error）；镜像树基线 rc=0 + existsSync=false |
| 3 | 上项的处置选择（本批改 fail / 随 PR-0 / 不动） | **不替用户拍板**，只给选项与代价 | ✅（视觉件 §6 探针行 + §11 F8；工单件 §13.4） | ❌ D2 待拍板 | 选项本体在视觉件 §11 F8 行末；证据在 §14.2 |
| 4 | V4 实拍判据「本机截图通道阻塞」 | **重定性**：通道成立（headless Chrome + CDP，零依赖），14 张已取 | ✅（视觉件 §7 V4 行 + 工单件 §13.4） | ⚠ **部分**：图已取、已自判，**本道仍不过**（三条理由见视觉件 §7 V4 行）⇒ 需用户验收才算收 | §14.3 逐张表（sha / 几何 / 异常 0）；shot-v4.mjs |
| 5 | 窄档 768 / 375「无横向滚动」判据未取 | 真实视口首帧即目标宽（从通道形状上消除 F6 那一型），**hScroll 全档 false、overflowSample 全空** | ✅（视觉件 §7 V4 行 / web/README） | ✅ | §14.3；命令：`node .tmp-scratch/ap-visual/shot-v4.mjs` |
| 6 | CJK 回落脚本观感未实测 | 逐节点取平台字体（479 扫 / 292 栅格化），**全部 isCustomFont=false**，实际落 Microsoft YaHei / Cascadia Mono / NSimSun / Noto Sans SC | ✅（视觉件 §2 字体行 / web/README L32） | ✅（原宣称从断言升为实证） | §14.4；控制组先证 `document.fonts.check` 无判别力 |
| 7 | 「一屏读完 30 盏」与实取值矛盾（scrollHeight vs innerHeight） | 四档 × 三选项全部现算（内存 what-if，**未动样式文件**）⇒ B/C 作为「让它成立」的选项被证伪，**只剩 A** | ✅（视觉件 §2.1 那行 + §11 F1） | ⚠ **判据本身未改**（措辞属产品决断）⇒ 待拍板，但现在可一句话答 | §14.5 逐档表；probe-gridwidth.mjs |
| 8 | razor-edge「容器实宽 1328.80px、只差 3.2px」 | 真实视口重取为 **1318 / 差 14px**，四处下游随动（旧值保留标不得当现值引） | ✅ | ✅ | §14.5 后半 |
| 9 | 视觉件 §6 反证表：断言 4 三子句未逐子句成行；探针行是推定不是逐口 | 补成逐子句成行 + 探针行改逐口实取（方向是**补表不是削脚本**） | ✅ | ✅（14/14 有效 + 探针 1 格，终态 rc=0） | §14.7 第 ⑪ 行；`node .tmp-scratch/ap-visual/mutate-v1.mjs` |
| 10 | 视觉件 §11 F8 全称句射程（只能对 `LAMP_GROUPS` 一口成立） | 已收窄为逐口读数，全称句不再成立 | ✅ | ✅ | §14.2 + §14.6 第 1 条 |
| 11 | 视觉件 §7 V1 行与实物不同步（原文仍写「§6 反证表**六格**」） | 就地标出不同步，**不改判据原文**（换成另一个数仍是同一个坑） | ✅ | ❌ D1 待拍板（建议改为「全部行，行数以该表与脚本为准」） | 视觉件 §7 V1 行；格数以脚本派生计数行为准 |
| 12 | 三刀体量数字未现取（上一版拿旧值与一句错话入库） | 按**物理行**现取 + 订正「刀①/刀② 是硬值」只对刀② 成立 | ✅（工单件 §8.1 + §13.4 + 本节 §13.6 指针） | ✅（数字可复跑）；**但两处置选项待拍板** | §14.7 末行；命令：`foreach … (Get-Content <文>).Count` + `git diff --numstat` |
| 13 | 工单件 §13.4 缺第六批行（随动表自己漏随动） | 第六批行原在；本批另补 §8 的第六批行（视觉件侧）与 §13.4 第七批六行 | ✅ | ✅ | 工单件 §13.4 末尾 / 视觉件 §8 |
| 14 | 顶层 docs 索引：三件索引行 + 提及数口径段未随动 | 已随动，并当场订正本批自己写的两处计数（「加五行」→六行；「四支 harness」→改指 §14.7 附行） | ✅ | ✅（G7 8/9/11 复跑同值） | §14.7 第 ⑧ 行；命令：`git grep -o --untracked -- <令牌>` |
| 15 | 分支模型八行读数未复跑 | 已复跑：**七行逐字同值**，**一行环境未达**（见下行 18） | ✅ | ⚠ **部分** | §14.1 |
| 16 | 分支模型 (a)/(b)（集成分支无对象 / 切点 / 合 main） | 给选项与代价，**不替拍板**；本批零 git 动作 | ✅（工单件 §8.1 + §13.4 + 取证件 §14.1） | ❌ D2 待拍板（合 main 另需用户显式批示） | §14.1 末段 |
| 17 | 真库与真 SSE 流（页上每个数字都是假数据） | **射程外**：需开工授权扩到后端联通，本批未开新方向 | ✅（已在多处标为射程外） | ❌ 未做（非本批授权） | 工单件 §13.4 射程行 |
| 18 | `git ls-remote --heads company` | **环境未达**：rc=128（内网 SSH 超时）。需在内网可达机器上跑同一条命令才能收 | ✅ | ❌ 未达（不得读成已复核） | §14.1 第二行 |
| 19 | `make ci-web` 目标未建 | 未建——它是 **PR-0 交付物**（工单件 §9.3 已定死形），不属本批「收欠项」射程 | ✅ | ❌ 未做 | 工单件 §9.3 |
| 20 | 全库错字 / 形状复扫（旧版无任何可复跑手段） | 新建 `typo-scan.ps1` 五道并跑到终态：**T1=2 / T2=18 / T3=0 / T4=0 / T5=0**（逐条定性完）；**它共拦下三处真破表 + 一处错指**（G8 拦不到列数那一型）；**第四轮终验复跑逐字同值** | ✅ | ✅（命令与读数齐） | §14.7 附行 B；命令：`powershell -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/typo-scan.ps1` |
| 21 | 本批新引入的坑（不靠上一批清单，靠本批自己现取） | G6 被一条带 docs/ 前缀的**分支名**推漂（140/70/6 ⇒ 139/69/5）；**三处破表（其中两处本批引入：未转义竖线 + 新表表头五列对四列数据行）+ 三处计数被后续动作推漂 + 两处自写错字** | ✅ | ✅（均已当场复跑归位：T4=0 / 假边已去反引；G6 现值以行 ⑦ 末句 141/69/5 为准） | §14.6 自犯表 + §14.7 第 ⑦ 行 + 附行 B |

⇒ **本批能自证的已自证（行 1/2/5/6/8/9/10/12/13/14/20/21）；属拍板项的未替用户定（行 3/7/11/16）；属环境或射程的如实标未达（行 4/15/17/18/19）**。待拍板四项（三口 throw 处置 / 一屏读完 A-B-C / 三刀体量 / 分支模型 (a)/(b)）**本批未新增也未推翻**，只把证据补厚。⚠ 末轮（10:13）复跑后，**其余读数一个都没动**：G1=0 / G2=7 / G3 True / G4・G5 rc=0 / G7 8・9・11 / G8 全 0 / check-tokens・mutate-v1 逐项同值 / T1=2・T2=18・T3=0・T4=0・T5=0（15 标签）；**唯一在漂的就是 G6 的 total 与本件行数**（它俩由本节自己的文字推动，见 §14.7 第五轮段）—— 这正是上段那句「不得引具体数作硬约束」的现形。

⚠ **本表（§14.8）之后有第八批（下一节 §15）**：行 **2/3/7/9/11/12** 的「待拍板」状态在第八批已收起，**历史读数与当时的判定一律不追改**（它们是取证链），只在下述位置加指针 —— 每项的落地读数与改法都在 **§15**，不在本表里重写。

---

## 15. 第八批（2026-10-31）：四项拍板（①②③⑤）落地的取证

**定位：** 拍板落地批。§12–§14 的形状是「把证据补厚、等用户定」，本节是「用户定了之后，落地在屏上留下了什么读数」。格式仍按 evidence-format §1 五字段 + §3 强度分档；新增探针的非空转反证按 §4。

**拍板来源（一句话，不美化）：** 用户 2026-10-31 的原话是「**是的，继续接下来任务**」，它批准的是上一窗口给出的**方案 A + 推荐项清单 ①②③⑤**，**不是逐项专批**。⇒ 所以本节每一项都要能回答「它对应清单里的哪一项」，15.1 那张表就是这张对照；对不上的动作就是越权。

**读数绑定 rev：** `d140f91f`（分支 feat/nl2sql-ttl-and-006-slim）。⚠ 本节**写下时三刀尚未提交**（提交时刻与 rev 回填在 §15.12，没落到那一节前本节都是「未入库」状态）；后端目录对该 rev 的 diff 在本节每一轮复跑里都是 **0 行**（G1，逐轮读数在 §15.9）。

**取数时刻：** 2026-10-31，逐表标注。⚠ **行数/体量/引用边三类一律「量级 + 引用前重取」**，重取命令就写在每张表的头句里；这三类在本批被自己的文字推动了四次（见 §15.10 自犯表末两行）。

**前置（字段 5）：** Node **v24.12.0**、零安装依赖（镜像树探针只读文件、不装包）；门禁断言 6 的四个派生源（两层 `HealthResponse`、`StreamEventType` Literal、router 直发字面量）在 `d140f91f` 树上可读。

### 15.1 四项拍板 ↔ 落地件 ↔ 分档（对照表）

| 清单项 | 用户批的是什么 | 落地件（改了什么） | 决策分档 | 落地读数在 |
|---|---|---|---|---|
| **①** | 三口 `throw` 统一改 `fail.push`，**同批**带上「读不到源即跳过该项双向比较」；`mutate-v1` 探针格语义随动但**行保留不删** | 门禁脚本 `web/scripts/check-tokens.mjs`（+25 行）；变异脚本 `mutate-v1.mjs`（gitignored）；视觉件 §6 / §11 F8 随动 | **D1**（可逆 + 中影响：动的是 POC 期未入库的门禁脚本，不是后端契约） | §15.2–§15.5 |
| **②** | 「一屏读完 30 盏」取 **A**：措辞改「一页内读完、允许滚动」 | 六处文字（§15.6 清单）；**一个样式值未改** | **D1**（产品文案，一句话可推翻） | §15.6 |
| **③** | 文档轨**明示豁免** + 代码两刀登记为**带理由的知情超限**（不是「就地重切成 9–10 个小 PR」） | 工单件 §8.1 建议 2 与 §13.4；本件只取体量 | **D1 带复审触发条件**（动的是「承诺」不是代码；三条触发条件见 §15.7） | §15.7 |
| **⑤** | V1「六格」/ V4「6 张」判据改为**不抄数形状** + 全库引用随动 | 视觉件 §7 两行、§8 表一行、工单件两处、web/README 一处 | **D1**（判据原文是下游要引的东西，所以当时等拍板才动） | §15.8 |
| （在册）**分支模型 (a)/(b)** | 方案 A = 本地建 `feat/web-visual-poc`（切点 `d140f91f`）、按三刀提交、**不 push / 不碰 main / 不解禁公开镜像** | 见 §15.12（本节写下时未执行） | (a) **D1 已批**；(b)（推内网集成分支 / 合 main）仍 **D2 未执行** | §15.12 |

⇒ **本批未新增待拍板项，也未推翻任何一条既有判据文字**。⑤ 那个方向要特别说明：它看起来像「把判据改成能过」，实际是**加严**（§15.8）。

### 15.2 ① 的实现形状（逐口坐标，改前进/改后出口）

取法：`Select-String -Path web/scripts/check-tokens.mjs -Pattern 'return null|fail.push|⚠ 跳过比较'`（行号随该文件后续改动漂，引用前重取；本表时刻 **2026-10-31 本轮**，该文件物理行 **222**）。

| 读取口 | 改前出口 | 改后出口 | 坐标 | 为什么这么改 |
|---|---|---|---|---|
| `dictKeys`（`EVENTS` 与 `LAMP_WHY` 共用一支函数） | **throw** | `fail.push` + `return null` | L179–186 | rc 同为 1 时唯一可分的读数是 stdout 有没有失败清单；throw 那条只有 stderr 栈 |
| `healthFields`（两层 `HealthResponse` class 头共用） | **throw** | `fail.push` + `return null` | L147–153 | 同上；且这一口失败污染的是**共享源侧**（见下行） |
| `LAMP_GROUPS`（第六批就从 throw 改过 fail） | fail.push | **不变**，只在失败行文案尾部补「分组项双向比较已跳过」 | L187–188 | 让「报失败」与「声明跳过」在同一行里可读，不靠人记口径 |
| `StreamEventType` Literal 读不到 | fail.push | **不变**，同批补「事件项双向比较已跳过」 | L135–136 | 同上 |
| `cmp`（三项比较共用） | 无条件逐项比 | 任一侧为 `null` ⇒ `note.push` 一条「⚠ 跳过比较」后 `return` | L198–209 | 跳过必须**报得出**：静默跳过等于把断言拆空，那正是「为凑绿放宽前置条件」的另一副面孔 |
| `rd` / `readText` 的**文件级 ENOENT** | throw | **有意不收**（注释在 L125–127） | — | 文件在不在 vs 文件里形状变没变是两类失败；后者有可跳过的对象，前者没有，吞成 fail.push 只丢掉 Node 自带的堆栈定位 |

**三条实现事实，缺一条上面那张表就读不准**：
1. 读不到返回的是 **`null` 而不是 `[]`**（L152 / L183 / L191 / L194）。`[]` 会活着走进 `cmp` 被逐项报成缺项/多项 —— 这一条不是推测，§15.5 把它当成反证对象量过了。
2. `FIELD_SET` 的污染范围比 `dictKeys` 大（L170：任一层读不到 ⇒ 整个派生字段集不可信 ⇒ 分组项与说明项**同时**跳过）。⇒ 镜像树探针里 `healthFields` 两口的**期望跳过行数 = 2**，`dictKeys` 两口 = **1**。这个不对称是判据的一部分，不是实现细节。
3. 新增了一个 `note` 出口（原来只有 `fail`）。它让「跳过」在 stdout 里是一行可读文本，因此**可被探针数**（§15.4 的「跳过行/期望」两列就是这么来的）。

### 15.3 ① 就地反证：`mutate-v1.mjs` 十六格逐字（实取时刻 2026-10-31 本轮）

命令：`node .tmp-scratch/ap-visual/mutate-v1.mjs`（该脚本住在 gitignored 目录，**不入库也不计刀**，与 §14.7 附行 A 同性质）。

| 变异格 | 变异后 rc | 是否命中该格断言 | 撤销后 | 失败段首行 |
|---|---|---|---|---|
| 断言1 色值字面量 | rc=1 | 命中断言1 | 复跑 rc=0 |   · 断言1 \web\src\styles\base.css 出现色值字面量：#ff0000 |
| 断言2 引用未登记 | rc=1 | 命中断言2 | 复跑 rc=0 |   · 断言2 引用了未登记令牌 --nope-9 |
| 断言3 孤儿令牌 | rc=1 | 命中断言3 | 复跑 rc=0 |   · 断言3 孤儿令牌 --orphan-probe（登记了无人引用；漂着的令牌下一批会被当成可调用的值） |
| 断言4 裸间距 | rc=1 | 命中断言4·含子句 | 复跑 rc=0 |   · 断言4 \web\src\styles\base.css padding:7px 用了裸尺寸，只允许 var(--sp-*) |
| 断言5 dark 双写漂移 | rc=1 | 命中断言5 | 复跑 rc=0 |   · 断言5 dark 双写漂移（1 条）： |
| 断言6 字典缺项 | rc=1 | 命中断言6 | 复跑 rc=0 |   · 断言6 事件图例字典 缺项（派生自源但字典没有）：done |
| 断言6 字典多项 | rc=1 | 命中断言6 | 复跑 rc=0 |   · 断言6 事件图例字典 多项（字典有但源已不产出）：bogus_evt |
| 断言1 独立灯页色值 | rc=1 | 命中断言1 | 复跑 rc=0 |   · 断言1 \web\poc-health.html 出现色值字面量：#ff0000 |
| 断言6 灯阵缺项 | rc=1 | 命中断言6 | 复跑 rc=0 |   · 断言6 /health 分组字典 缺项（派生自源但字典没有）：langfuse_enabled, langfuse_ready, otel, otel_status |
| 断言6 灯阵多项 | rc=1 | 命中断言6 | 复跑 rc=0 |   · 断言6 /health 分组字典 多项（字典有但源已不产出）：bogus_lamp |
| 断言4 非三档字重（子句 font-weight） | rc=1 | 命中断言4·含子句 | 复跑 rc=0 |   · 断言4 \web\src\styles\base.css font-weight:700 只允许 400/500/600（未打包的字重会静默回落） |
| 断言4 裸行高（子句 line-height） | rc=1 | 命中断言4·含子句 | 复跑 rc=0 |   · 断言4 \web\src\styles\base.css line-height:1.8 只允许 var(--lh-*) / var(--ls-*)（第四批新立令牌族的子句） |
| 断言4 裸字距（子句 letter-spacing） | rc=1 | 命中断言4·含子句 | 复跑 rc=0 |   · 断言4 \web\src\styles\base.css letter-spacing:0.02em 只允许 var(--lh-*) / var(--ls-*)（第四批新立令牌族的子句） |
| 读不到灯阵字典（fail 口） | rc=1 | 命中断言6·含子句·跳过成立 | 复跑 rc=0 |   · 断言6 poc-health.html 里读不到 const LAMP_GROUPS（灯阵字典坐标变了，先核对再改门禁；分组项双向比较已跳过） |
| 读不到事件字典（源失败行 + 跳过） | rc=1 | 命中断言6·含子句·跳过成立 | 复跑 rc=0 |   · 断言6 poc.html 里找不到 const EVENTS（屏上字典坐标变了，先核对再改门禁；该项双向比较已跳过） |
| 读不到说明字典（跳过不外溢） | rc=1 | 命中断言6·含子句·跳过成立·他项未污染 | 复跑 rc=0 |   · 断言6 poc-health.html 里找不到 const LAMP_WHY（屏上字典坐标变了，先核对再改门禁；该项双向比较已跳过） |

计数行与终态（脚本原样输出，非手数）：`反证格：16/16 有效（判据三段：命中断言号/子句·源失败时该项跳过·他项不被污染）` / `全撤销后终态：rc=0` / `✅ 视觉门禁通过（定义 91 / 引用 91）`，脚本 **rc=0**。

**形状差异要说清（否则后人拿 §14.7 第 ⑪ 行的 14+1 来比会以为本批削了格）**：第七批是 **14 反证格 + 1 探针格（不计入有效数）**；第八批是 **16 格全部计入**。变化来自原探针那一格按「三口 + 对照」拆开：它过去一句话覆盖三口却只能报一个读数，① 落地后三口各自的期望可分（`LAMP_GROUPS` 对照 1 行、事件字典 1 行、说明字典 1 行），于是**拆成三格** ⇒ 13 + 3 = 16。**没有一格被删**，判据从一段扩成三段（第三段「他项不被污染」只加在说明字典那一格，因为它是本批唯一能就地证的「不外溢」样本 —— `healthFields` 的外溢要打到后端源，见 §15.4）。

### 15.4 ① 镜像树逐口复核（`probe-throw2.mjs`，实取时刻 2026-10-31 本轮）

命令：`node .tmp-scratch/ap-visual/probe-throw2.mjs`。方法是第七批立的那一条（镜像树副本 + 基线自证 + 用后即删 + 后端 diff 复核），本批是**第二次复用且同样跑绿** ⇒ 它可以当固定取法直接引，不再是一次性侥幸（这条结论已在视觉件 §11 F8 的随动句里登记）。

**判据五项**（比第七批多两项，因为 ① 之后「报得出」已不是考点，考的是「报得准」）：rc=1 / 有失败段且命中本口声明的那条源失败行 / stderr 无栈 / **逐项误报行数 = 0** / **「⚠ 跳过比较」行数 = 本口期望值**。

基线自证（缺它下面所有读数作废）：`镜像树基线：rc=0  stdout含「视觉门禁失败」=false`，stdout 末行 `✅ 视觉门禁通过（定义 91 / 引用 91）`。

| 读取口 | 变异后 rc | 判读 | 逐项误报 | 跳过行/期望 | stderr 栈 | 撤销后 |
|---|---|---|---|---|---|---|
| LAMP_WHY（dictKeys 第二口） | rc=1 | 成立（fail 口 + 跳过生效） | 0 条 | 1/1 | 栈无 | 撤销后 rc=0 |
| healthFields 第一层 class 头 | rc=1 | 成立（fail 口 + 跳过生效） | 0 条 | 2/2 | 栈无 | 撤销后 rc=0 |
| healthFields 第二层 class 头 | rc=1 | 成立（fail 口 + 跳过生效） | 0 条 | 2/2 | 栈无 | 撤销后 rc=0 |
| LAMP_GROUPS（原 fail 口·对照） | rc=1 | 成立（fail 口 + 跳过生效） | 0 条 | 1/1 | 栈无 | 撤销后 rc=0 |

收尾两行（脚本原样）：`逐口：4/4 成立（判据五项：rc=1、有失败段且命中源失败行、无栈、误报行 0、跳过行等于期望）` / `镜像树已删除：existsSync=false（必须 False）`，脚本 **rc=0**。

⚠ **为什么跳过行要两列分计（误报行 + 跳过行）**：只数跳过行会把「两侧都不比了」也读成绿灯 —— 那是把断言拆空而不是把误报关掉。两支必须同时成立：**误报 0 且跳过行数 = 期望**，且期望值本身在 §15.2 第 2 条里有出处（`healthFields` 污染共享源侧 ⇒ 2；`dictKeys` 只污染自己 ⇒ 1）。

### 15.5 R1 那一行：「只换出口不跳过」被实测否证（新建 `probe-r1.mjs`，2026-10-31 本轮）

视觉件 §6 表后那句「两件必须同一批做」是一句**因果陈述**。按本件反复点名的纪律（因果句不跑就写 = 自犯），这句不能只留在散文里 ⇒ 现做一支反证探针：在镜像树里**把第八批的跳过分支拆掉**（只拆 ① 改过的那两口 `return null;` → `return [];`，其余一律不动），再重打同样的四个变异。

命令：`node .tmp-scratch/ap-visual/probe-r1.mjs`。自证三格（缺一格后面无从归因）：`基线（镜像树原样）：rc=0` / `产品脚本里 return null; 出现 2 次（期望 2）` / `拆跳过后、未变异：rc=0  跳过行=0` —— 最后那格证的是「拆跳过本身不改变绿灯形状，它只在源读不到时起作用」。

| 变异口（跳过被拆掉后） | rc | 误报行 | 误报键名 | 跳过行/现产品应为 | 报出的派生集（应为 12 / 30） |
|---|---|---|---|---|---|
| EVENTS（对话页事件字典） | rc=1 | 1 行 | 12 个 | 0/0 | 派生集（不写死）：事件 12 类 / 字段 30 个 |
| LAMP_WHY（灯页说明字典） | rc=1 | 1 行 | 30 个 | 0/0 | 派生集（不写死）：事件 12 类 / 字段 30 个 |
| healthFields 第一层 class 头 | rc=1 | 2 行 | 26 个 | 0/0 | 派生集（不写死）：事件 12 类 / **字段 17 个** |
| healthFields 第二层 class 头 | rc=1 | 2 行 | 34 个 | 0/0 | 派生集（不写死）：事件 12 类 / **字段 13 个** |

⇒ **R1 成立，但成立的理由比原句说的更硬**。原句只说「炸成整屏误报」；实取到的形状是两层：
1. **误报量**：一次变异产出 **12 / 26 / 30 / 34 个假键名**（跳过在位时同一变异是 0 条，见 §15.4），逐条判读它们才是真实代价 —— 报错本身不告诉你是「坐标变了」还是「字典写错了」；
2. **更坏的一半不是噪声，是错诊**：`healthFields` 那两口拆掉跳过后，派生集**从 30 静默降到 17 / 13**，而比较照跑，报出口的是「/health 分组字典 多项（字典有但源已不产出）：…」—— 一个方向完全反了的结论（源少了一层，被判成屏上多了十几项）。这正是门禁脚本头注释 L121–124 写的那句「反而把人往『字典写错了』的方向引」的实形。

⇒ 所以「同批带上跳过」不是锦上添花：少了它，`fail.push` 改造后的门禁**比原来走 throw 时更危险**（throw 至少不假装自己比过）。这一条是本批唯一由**新实验**得到的结论，其余三项都是既有登记的兑现。

### 15.6 ② 措辞的逐处随动清单（六处 + 一处代码注释）

判据本体在视觉件 §2.1（L130 末句）；下表是**除它之外**被同一句话推着改的地方。复跑读数（本轮）：`check-tokens.mjs` rc=**0**（定义 91 / 引用 91），**一个样式值未改** —— 地板 260px 也原值。

| 处所 | 改前 | 现行（改后） | 备注 |
|---|---|---|---|
| 视觉件 §2.1 L130 | 「一屏读完 30 盏」这一半句在两个页面都不成立（登记为矛盾，等 A/B/C） | 判据现行措辞为「**一页内读完 30 盏、允许滚动**」，「一屏」不再当视觉预算用；B/C 标为「已按实测证伪而放弃」 | 判据本体；scrollHeight 读数**不作废也不回退**，身份换成「滚动距离的现值」 |
| 视觉件 §11 F1 L433 | 三个选项待定，「只剩 A 与现实一致」 | 「**第八批 ② 已按本句取 A：措辞已改，上面三个选项的射程到此关闭**」 | 重开 B/C 需新的真实档位读数 |
| 工单件 §7 PR-4 行 L166 | 「到本批仍未成立」+ 待拍板 | 「第八批 ② 已拿到结论：取 A」+ 逐处清单指向本节 | 工单行的完成判据（每盏灯可追溯 + V4/V5/V7）**一字未动** |
| 工单件 §13.1 第 2 格 L536 | 「一屏能读完的灯阵」 | 「**一页内能读完的灯阵、允许滚动**」+ 出处（第八批 ② 拍板，读数在视觉件 §2.1 / 取证件 §14.5） | 需求登记格：这是需求原文，改它必须带拍板出处 |
| web/README L141 | 「『一屏读完 30 盏』仍未成立」 | 旧句划掉 + 「现行措辞改为『一页内读完 30 盏、允许滚动』」 | 历史读数 1410/2085/3550 全部保留 |
| web/poc-health.html L32 | 页内提示写「一屏读完全部字段」 | 写「**一页内读完全部字段（允许滚动）**」并就地标注「原措辞由第八批 ② 按拍板改掉，本页样式值一个未改」 | 唯一一处**面客文本**（其余都是文档） |
| `events.css` L122–123（注释，非判据） | 注释引原句「…一屏读完 30 盏」 | 加一行注明「该句后半已由第八批 ② 改措辞，**地板这个值未动**」 | 物理行 191 → **192**（+1 行注释，样式规则零改） |

⇒ **本项没动一个 hex、没动一条规则、没动一枚令牌**（终态 rc=0 且定义/引用仍 91/91 就是这一句的反证：若样式被动过，那两个数不会一动不动）。

### 15.7 ③ 体量：三刀现值、定案口径、与三条复审触发条件

取法（`volume8.ps1`，实取时刻 2026-10-31 本轮）：未入库新文件取全文 `(Get-Content <文> -Encoding utf8).Count`；已跟踪的改文件取 `git diff --numstat` 两列之和。⚠ **不得与 `Measure-Object -Line` 混引**（它不计空行，`tokens.css` 给 193 而物理行 217 —— 第七批撞过的那条命令级坑）。

| 刀 | 构成（本轮现取） | 行数 | 对 400 行申报项 |
|---|---|---|---|
| ① | `tokens.css` 217 + `base.css` 299 + `events.css` **192** + `web/README.md` **144** | **852** | **知情超限**（带理由，不是豁免） |
| ② | `poc.html` 267 + `poc-health.html` 180 + `check-tokens.mjs` **222**（① 三口 +25） | **669** | **知情超限**（带理由） |
| ③ | 取证件 **1470** + 视觉件 435 + 工单件 diff **117** + 顶层索引 diff **10** | **2032** | **文档轨明示豁免** |
| 合计 | — | **3553** | 三刀总和只作参考，不是判据 |

**定案口径（三条，都在工单件 §8.1，本节只给读数与出处）**：
1. **400 行不是技术强制** —— 取证命令：`git grep -n "400" -- scripts/ .github/ Makefile pyproject.toml` 本轮实取 **5 行命中，全在 `scripts/opencode_gateway.py`，且全是 HTTP 400 状态码**（不是体量门）。⇒ 仓内**没有任何一道门禁或脚本校 PR/提交的行数**，所以它降级为「申报项」；硬判据换成「**提交后被它承诺的门禁仍能跑且非空转**」（= 本节 §15.3/§15.4 那两道，加 §15.9 八道）。
2. **代码两刀 = 知情超限**（不重切）。理由：刀① 的 852 行里 **516 行是两个 CSS 令表面 + 一个 README**，拆开后每一片都失去「同一批令牌定义与它的引用面同处一批」的可核性；刀② 669 行里两个宿主页是 POC 面客件、与 `check-tokens.mjs` 是一对（脚本读的就是这两页的字典）。⚠ 拆与不拆都是**可逆**的（分支未推、可原地重切），所以它是 D1 不是 D2。
3. **文档轨 = 明示豁免**。理由：取证台账的行数与其证据量同向（本节自己从 1396 涨到 1470 就是这一句的现场），拿代码体量去削文档等于删证据。豁免写法是把「不适用」写在登记处而不是默认不校 —— 默认不校就是没拍板。

**三条复审触发条件**（按《分支卫生》第 2 条：登记必须带复审触发条件，没有复审条件的登记不许写）：① `make ci-web` 进 CI 且其中出现**强制**体量检查；② 任一代码刀再涨 50%（刀② 669 ⇒ 破 **1000**）；③ 刀③ 混入非纯文档内容（一旦含 `.py`/`.mjs`/样式，文档轨豁免立即失效，那一刀要重新按代码轨判）。

### 15.8 ⑤ 判据改为不抄数形状：改法与「加严非放宽」的定性

| 判据 | 旧原文 | 新原文 | 为什么这是加严 |
|---|---|---|---|
| V1 | 「§6 反证表**六格**逐格实取」 | 「§6 反证表**全部行逐格实取**（行数以该表与脚本 `MUTANTS` 为准，判据不抄具体数）」 | 旧文只要求六行有读数；新文要求**每一行**都有读数。本轮实测是 **16 格**（§15.3），旧措辞下「六格全过」在新措辞下**不自动成立** |
| V4 | 实拍「= **6 张**」 | 「双主题 × 三断点 × **每个页面**的全组合实拍（张数由『主题 × 断点 × 页数』导出、以实拍台账为准，判据不抄数）」 | 第六批实拍实取 **14 张**（§14.3）：旧文的 6 是与实物脱节的硬数；新文把导出式交给形状本身，页数一旦变化判据不跟着漂 |

⚠ **两条边界必须同读，否则 ⑤ 会被误记成「放宽」**：
1. **改的是判据文字，不是被检物**。本批**未删一行反证格、未改一个样式值、未缩一张实拍** —— 与「把实物削到与判据齐平」正好相反（AGENTS.md 红线「禁止为过测试而改测试」在这一型上的变体就是削实物）。
2. **不抄数比换成另一个更准的数也更严**：更准的数会被下一批推漂（V1 那个「六」当年就是准的），而不抄数形状把这件事交给脚本与台账自己，要求从「凑够 N 行」变成「一行都不许没读数」。

⇒ **⑤ 不改变 V4 仍未过的事实**。它只收了「判据原文与实物不同步」那一条理由（工单件 L172 已把该条划掉并注明理由），剩下两条不变：实拍跑在静态宿主页而非判据绑的 `pnpm` 通道 + 最终观感判读属人。

### 15.9 本批终跑（八道 + 样式两道 + 形状复扫）

**首轮**（本节 §15.4–§15.8 写下之后、§15.9–§15.12 写下之前，2026-10-31 本轮实取）。命令逐字：`powershell -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/gates4.ps1`、`node web/scripts/check-tokens.mjs`、`node .tmp-scratch/ap-visual/mutate-v1.mjs`、`node .tmp-scratch/ap-visual/probe-throw2.mjs`、`node .tmp-scratch/ap-visual/probe-r1.mjs`、`powershell -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/typo-scan.ps1`、`powershell -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/volume8.ps1`。

| 门禁 | 第七批终值（§14.7） | **第八批首轮实抄** | 差值定性 |
|---|---|---|---|
| ① G0 HEAD / 分支 | `d140f91f` / feat/nl2sql-ttl-and-006-slim | **逐字同值** | 本批至首轮仍零提交（三刀在 §15.12） |
| ② G1 后端目录对 `d140f91f` 的 diff | **0 行** | **lines=0** | 红线：本批动过门禁脚本但**未碰一个后端字节**；两支镜像树探针（§15.4 / §15.5）都是副本上变异、用后即删 |
| ③ G2 `git status` 非 docs 条目 | 7 条（全在 `web/`） | **lines=7，逐字同集** | ① 只改了已在集内的 `web/scripts/check-tokens.mjs`，**未新增一个入库文件** |
| ④ G3 `Test-Path web` | True | **True** | 不变 |
| ⑤ G4 `check_doc_sync.py` | rc=**0** | **rc=0**·`✅ 文档同步校验通过（0 警告）` | 不变；⚠ 口径同 §12.12 / §13.6：它根本不扫本批这几份文档里的路径引用，它的绿不能当「互指已证」 |
| ⑥ G5 `ruff check .` | rc=**0** | **rc=0**·`All checks passed!` | 不变（本批仍未动 `.py`；取证脚本住 gitignored，这道不扫） |
| ⑦ G6 就地引用边自查 | 行 ⑦ 末句现值 **141 / 69 / 5** | **142 / 69 / 5**（BAD 五条同旧集，含那个故意改坏的夹具） | ⚠ **total +1、unique 与 unresolved 不动** ⇒ 同一目标多写一次（真边重复计数，不造 BAD，保留反引）。**本批未能逐条归因**：+3 是 §15 写下前从 139→142 跳的，只确证其中一处为工单件 §8.1 新增的那条 docs 路径，另两条未逐一定位 ⇒ **如实登记「未逐条归因」而不编解释**（§14.7 第五轮那一型同样只到「哪个文件第几次出现」的粒度） |
| ⑧ G7 提及数 | 8 / 9 / 11 | **8 / 9 / 11** | 三值不动且构成未动 |
| ⑨ G8 表格完整性 | 四份全 **0** | **四份全 0** | ⚠ 同 §14.7 行 ⑨ 的提醒：它拦不到列数那一型，列数靠下面 T4 |
| ⑩ `node web/scripts/check-tokens.mjs` | rc=**0**：定义 **91** / 引用 **91**；事件 **12** / 字段 **30**；断言 6 三行 **12/12、30/30、30/30** | **逐字同值（rc=0）** | ① 改了脚本的失败出口但没改任何一条断言的判定 ⇒ 这四个读数**应当不动**，动了就是改错东西 |
| ⑪ `node .tmp-scratch/ap-visual/mutate-v1.mjs` | 反证格 **14/14** + 探针 **1** 格 + 终态 rc=**0** | **16/16 有效**（探针格已翻面，判据三段）+ 全撤销终态 rc=**0** + 末行 `✅ 视觉门禁通过（定义 91 / 引用 91）` | 与 §15.3 同一轮的数 |
| ⑫ `node .tmp-scratch/ap-visual/probe-throw2.mjs` | 四口均为 throw（当时只报「失败段全空」） | **基线 rc=0 + 逐口 4/4 成立 + 误报 0 条 + 跳过行 1/2/2/1 等于期望 + existsSync=false** | 本批新增的两列（误报 / 跳过）就是 ① 的验收面 |
| ⑬ `node .tmp-scratch/ap-visual/probe-r1.mjs` | （本批新建，无对照行） | 三格自证齐（基线 rc=0 / `return null;` 计数 2 / 拆跳过未变异 rc=0）+ 四口误报 **12・30・26・34 个** + 派生集降到 **17 / 13** + existsSync=false | 它否证的是「只换出口不跳过」那个没选的方案（§15.5），不是产品形状 |
| ⑭ `typo-scan.ps1` | **T1=2 / T2=18 / T3=0 / T4=0 / T5=0**（提取 15 标签） | **T1=3 / T2=18 / T3=0 / T4=0 / T5=1**（提取 **16** 标签） | ⚠ **两个差值都是本批自己造的可定性项**，不是退步：・**T1 从 2 到 3** —— 多的那条是 L1344 把「溢出来」误写成「拓出」的**引用行本身**（本批改那一句时把它推进了词表命中面）；逐条 Grep 定性：**三条全是自指引用**（L1292・L1354 两处「木机」+ L1344 一处「拓出」），**无一条活错字**。・**T5 从 0 到 1** —— `mutate-v1` 本轮 16 格（标签从 15 变 16），新标签「读不到说明字典（跳过不外溢）」当时尚未被文档引用 ⇒ §15.3 把它逐字写出来后应归零（末轮验证这一条） |

**体量三刀（首轮同轮现取，命令：`powershell -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/volume8.ps1`）**：刀① **852** / 刀② **669** / 刀③ **1948**（取证件 1396 + 视觉件 435 + 工单件 diff 117 + 顶层索引 diff 10）⇒ 三刀总和 **3469**。⚠ **§15.7 那张表里的 2032 / 3553 是它写下时刻对「本节尚未落地」的本件行数的现取，而 §15.9–§15.12 又推了一次** —— 这就是 §15.7 第 3 条那句「台账行数与其证据量同向」的本批现场；**引用前重取**，不得拿 2032 当现值。

⚠ **末轮复核这一行的分项：括号里那四个加数不自洽**（1396 + 435 + 117 + 10 = 1958 ≠ 1948）。逐字回查首轮那份输出：117 是**工单件 107（98 加 9）+ 顶层索引 10** 的**合项**，被当成分项写了一次（正确的分项应是 107 与 10）；**而总和 1948 是脚本原样输出、是对的**（1396 + 435 + 107 + 10 = 1948）。⇒ 登在 §15.10 行 14；**历史那一句不遮掉**（要看得出错在哪一步，得留着错的那一句）。

**末轮**（§15.1–§15.12 全部写下之后跑的最后一轮，2026-10-31 实取；命令逐字与首轮那一句同）。逐道读数与差值：

| 门禁 | 首轮 | **末轮** | 定性 |
|---|---|---|---|
| G0 HEAD / 分支 | `d140f91f` / feat/nl2sql-ttl-and-006-slim | **逐字同值** | 末轮时三刀仍未提交（提交读数是 §15.12 的待回填项） |
| G1 后端目录 diff | lines=0 | **lines=0** | 红线守住；两支镜像树探针本轮都报 existsSync=false |
| G2 非 docs 条目 | lines=7 | **lines=7、逐字同集** | 本批未新增一个入库文件 |
| G3 `Test-Path web` | True | **True** | 不变 |
| G4 / G5 | rc=0 / rc=0 | **rc=0 / rc=0**（`文档同步校验通过`・`All checks passed!`） | 不变；⚠ G4 的覆盖面口径仍以 §12.12 那条为准（它不扫 docs 下的互指路径） |
| G6 就地引用边 | 142 / 69 / 5 | **142 / 69 / 5**（BAD 五条同旧集） | ⚠ **§15 后半与本段都没把边推上去** —— 这几段新增的位置指称全走「取证件 §15.x」这种**章节号 + 不带反引的普通文本**，一个 docs/ 开头的反引串也没写。这是 §14.7 第六轮那条口径的第二次正向执行（上一次是拿它写体量行，这一次是拿它写整节自犯表） |
| G7 提及数 | 8 / 9 / 11 | **8 / 9 / 11** | 同因：新增文字没重复那三个令牌 |
| G8 表格完整性 | 四份全 0 | **四份全 0** | 本节新增的三张表都过；⚠ 列数那一型仍靠下面 T4 |
| `check-tokens.mjs` | rc=0、定义 91 / 引用 91、事件 12 / 字段 30、断言 6 三行 12/12・30/30・30/30 | **逐字同值（rc=0）** | ① 改的是失败出口，这两轮都不该动；动了就是改错东西 |
| `mutate-v1.mjs` | 16/16 有效 + 全撤销终态 rc=0 | **16/16 有效 + 终态 rc=0 + 末行绿** | 与 §15.3 同一形状 |
| `probe-throw2.mjs` | 基线 rc=0・逐口 4/4・误报 0 条・跳过 1/2/2/1・existsSync=false | **逐字同值** | ① 的验收面可复跑，不是一次性读数 |
| `probe-r1.mjs` | 自证三格齐・误报键名 12・30・26・34・派生集降到 17 / 13・existsSync=false | **逐字同值** | §15.5 那条否证同理：它是可复跑的形状，不是当日偶发 |
| `typo-scan.ps1` | T1=3 / T2=18 / T3=0 / T4=0 / **T5=1**（16 标签） | **T1=5 / T2=18 / T3=0 / T4=0 / T5=0**（16 标签） | ✅ **T5 归零** —— 兑现首轮那一格写的「§15.3 把新标签逐字写出来后应归零，末轮验证这一条」。⚠ **T1 从 3 涨到 5**：多的两条都落在本件 **L1573 那一格**（它是首轮表行 ⑭ 里那句对两个错形的**引用**）⇒ 台账一开始引用错形，探针就把台账自己算进命中面。五条逐条核：三处「木机」（L1292・L1354・L1573）+ 两处「拓出」（L1344・L1573），**全是自指引用，无一条活错字**。⇒ 这一型是 §14.7 附行 B 那条 T5 的**反向版本**：命中会因引用而消失，也会因引用而出现 |
| `volume8.ps1` | 852 / 669 / 1948・total 3469 | **852 / 669 / 2169・total 3690**（刀③ = 视觉件 436 + 取证件 1610 + 两份 diff 共 123） | 刀①② 不动：样式三件与两个宿主页本轮一个字节未改（events.css 192 与 README 144 是 ②/⑤ 那两处随动的量，首轮就已含）；刀③ 从 1948 到 2169 就是 §15 全节 + 工单件 §13.4 那六行 + 顶层索引那三段写进去的量 |

⇒ **末轮没有一道门禁变红，也没有一个读数需要修产品代码去迎**；本批唯一的退步面是 T1 多出的两条自指引用，它已经在本格定性完。⚠ 本段写下之后 §15.10 还要补三行自犯、§15.11 要补本批新建的 harness 名 ⇒ **这三类数（本件行数 / 体量 / 引用边）的最后一轮读数在下一段，不在本段。**

**收尾轮**（末轮之后又做了字符级收尾：行 12/13 的实跑复证、四处随动的第二轮清理、§15.11 补 harness 名 —— 所以本批**真正最后跑的一轮不是上面那一轮**，是这一轮；2026-10-31 实取，命令逐字与首轮同一组，但**输出全部落盘再读**，取法见 §15.11 末段）：

| 项 | 末轮 | **收尾轮** | 定性 |
|---|---|---|---|
| G0 / G1 / G2 / G3 | `d140f91f`・lines=0・lines=7・True | **逐字同值** | 仍未提交（三刀在 §15.12）；红线未碰 |
| G4 / G5 | rc=0 / rc=0 | **rc=0 / rc=0** | 不变 |
| G6 引用边 | 142 / 69 / 5 | **142 / 69 / 5**（BAD 五条同旧集） | ⚠ 收尾轮新增的是**码点记法**（U+XXXX）与行号，一个 docs/ 开头的反引串也没写 ⇒ 这是那条口径的**第三次正向执行**（第一次写体量行、第二次写自犯表、第三次写这一整段） |
| G7 提及数 | 8 / 9 / 11 | **8 / 9 / 11** | 同因 |
| G8 表格完整性 | 四份全 0 | **四份全 0** | 本段新写的表过；⚠ 列数那一型仍靠 T4 |
| `check-tokens.mjs` | rc=0、91/91、12/30、12/12・30/30・30/30 | **逐字同值** | ① 改的是失败出口，本批三轮都不动才对 |
| `mutate-v1.mjs` | 16/16・终态 rc=0・末行绿 | **16/16・终态 rc=0・末行绿** | 可复跑，不是当日偶发 |
| `probe-throw2.mjs` | 基线 rc=0・4/4・误报 0 条・跳过 1/2/2/1・existsSync=false | **逐字同值** | 同上 |
| `probe-r1.mjs` | 自证三格齐・误报 12・30・26・34・降到 17/13・existsSync=false | **逐字同值** | 同上 |
| `typo-scan.ps1` | T1=5 / T2=18 / T3=0 / T4=0 / T5=0（16 标签） | **T1=7** / T2=18 / T3=0 / T4=0 / **T5=0**（16 标签） | ⚠ T1 从 5 到 7 的**两条增量全部落在本件 L1595**，也就是末轮那一格里对两个错形的**引用本身** —— 写下那句引用的时候，那句话自己就进了命中面。逐条核：四处「木机」（L1292・L1354・L1573・L1595）+ 三处「拓出」（L1344・L1573・L1595），**全是自指引用，无一条活错字**（登记为行 16） |
| `volume8.ps1` | 852 / 669 / 2169・total 3690 | **852 / 669 / 2195・total 3716**（刀③ = 视觉件 436 + 取证件 1636 + 两份 diff 共 123） | 刀①② 三轮不动（样式与两宿主页本批收尾轮零字节改动）；刀③ 2169→2195 就是 §15.10 行 12/13/14 的改写 + §15.11 那四支 harness + 本段的量 |
| **字符级复扫（本轮新建的两条读数）** | —— | `fix-e8b.mjs --check` 四型全 **0**（PLACEHOLDER / BU-SP-CHAO / CHAO-SP-BEFORE-CJK / C4-TO-CHAO）；`cp-neighbours.mjs 6284` 本件 **48** 处、右侧紧跟空格 **2** 处且两条都是合法形状 | ⇒ 行 13 的第二轮清理**已兑现为可复跑读数**，不是写在纸上的「已清完」。另：U+6728 本件复扫 **7** 处（行 10 当时记的是 5 处），逐条坐标 L1292×2・L1354・L1573・L1595・L1613・L1632，**全是引用、无活错字**；从 5 到 7 的两条增量分别是末轮那一格与本段 T1 那一格对自己的引用 —— 同一型，见行 16。⚠ **本行自己写下之后这个数还会涨**（每一格引用它都是一次上移），所以它只能当本轮读数用，引用前重取 |

⚠ **自指边界（本段也适用，且必须说清）**：本节 §15.9 的三段（首轮 / 末轮 / 收尾轮）各自都**不包含自己**的文字。收尾轮是「§15.10 行 12/13/14 写完、§15.11 补完」之后的第一次全套读数，但它**不包含本段自己与随后新增的行 15/16** ⇒ 那两类的终值只能到 §15.12 提交后的新一轮取证里去取（提交后 G0 / G2 本来就会变，那一轮顺带取本件行数与体量终值）。所以：**本段的三刀体量数（852 / 669 / 2195）是「刀③ 提交前」的上界估计，不是提交后的终值**，引用前按头句命令重取。

**入库轮**（刀①② 已提交、刀③ 提交前跑的最后一轮全套，2026-10-31 实取；命令逐字与首轮同一组，输出全部落盘再读 —— 取法见 §15.11 末段）。⚠ **这一轮的逐道读数只记在 §15.12 第 4 条一处**，本段不再把这些数写第二遍（写第二遍就要为填数多跑一轮，而那一格本身就是最终读数）。本段只记**与收尾轮的五条差值**及其定性：

・ **G0 从 `d140f91f` / 那条在册分支，变为 `2c13b001` / feat/web-visual-poc** —— 本批第一次有「已提交」进去的读数。⚠ 前三轮里所有「零提交」的陈述从这一刻起成为**历史值**，一律不追改（它们是取证链，不是现值）。
・ **G2 非 docs 条目从 7 降到 0** —— 原先那 7 条未跟踪的 web/ 文件因已跟踪而消失 ⇒ §15.12 自指边界第 ② 条的预言当场现形。G1 仍 **lines=0**，且这次是**带提交历史的可复跑事实**（逐刀取法在 §15.12 第 2 条），不再只是工作区里的承诺。
・ **T1 从 7 到 9**：两条增量都落在本件 **L1613**（收尾轮那一格里、对两个坏字形的引用自己）。9 条命中的坐标逐条为 L1292・L1344・L1354・L1573×2・L1595×2・L1613×2 —— 两种词型各 5 处与 4 处，**全部是引用、无一条活错字** ⇒ 行 16 那一型的**第四次上移**，也是行 16 末句「本行写下之后这个数还会涨」的当场兑现。
・ **T2 从 18 到 19**：多的那一条是本批改 web/README.md L144（那条入库陈述）时写进去的一个**目录相对**路径 —— 它按 web/ 目录读，而 T2 按**仓库根**解析 ⇒ 报 MISSING。它不是错指：同一文件 L20 那串没包反引号、L40 给的是根相对的完整命令。⇒ **本批不改**，理由与登记口径见**行 19**。
・ **体量**：刀① **852** / 刀② **669** 三轮不动（入库轮对 web/ 一个字节未改），刀③ 与 total 的现值只记在 §15.12 第 4 条；两份被改文档的 diff 合项从 123 到 **125**（工单件那三处随动的量）。

⚠ **入库轮同样不自含**：本段与行 19 写下之后本件行数还会涨 ⇒ 刀③ 体量与 total 的**最终值以填进 §15.12 的那一次运行为准**（填数不增行，所以那一次就是终值 —— 事后复跑 volume8 与 typo-scan 逐字同值，本批那句「填数不增行」当场拿到反证）。⚠ **收尾轮末句那句「终值只能到提交后的新一轮里去取」被本批自己修正了**：它预言的是「提交后」，实际是**刀③ 提交前**就取到了 —— 因为行 15/16 已落地、剩下的只有本段自己（原句不遮，它是当时真实的判断边界）。刀③ 提交后的 G0 / G2 仍属下一批首轮 —— 同一句边界在 §15.12 第 5 条，两处不冲突。

### 15.10 本批自犯表（逐条带当场发现方式与处置）

| # | 自犯 | 怎么发现的 | 处置与可复跑证据 |
|---|---|---|---|
| 1 | **写入链路把 U+6284（正字）换成 U+62C4（形近字），实测 8 处**，且 PowerShell 内联码点计数对同一串反向报 **0**（假阴性） | 先看屏幕上像错字 → 内联计数报 0 差点误判为「纯显示问题」→ 改写**落盘 Node 探针**按码点数，实取 `U+62C4=8 / U+6284=50` ⇒ 定性为真写坏 | 以错字为 original_text + replace_all 改回；纪律改为：**新文字里那个字一律写 CHAO 占位（两侧各带一个井号），由 `.tmp-scratch/ap-visual/fix-chao.mjs` 按码点落正字；验证只信落盘探针的码点计数，不信工具回显也不信内联计数**。本行不示例那个 token，理由是行 11 |
| 2 | 工具**输出渲染**也会把正字显示成形近字（与 #1 反向） | 同一份内容两次读取得到两种字形 | 同上：字形不可信，只信码点。⇒ 这一型的新知识：**两侧都可能变形，所以任何一侧的读数都不能单独当证据** |
| 3 | 上一版 `fix-chao.mjs` 的形近清理集填的码点是 **U+62C2（又一个不同的字）**，而真形近字是 **U+62C4** ⇒ **那条清理分支从未命中过（一次空转的“修复”）**；后果：工单件 L168 的一处活错字躲过了它 | 本批要在正文里写那个动词（「不 + 动词 + 数」那一型）时先按码点全库扫，实取 `U+62C4=1` 才定位到那处 | 两处都由 `.tmp-scratch/ap-visual/fix-e8.mjs` **按码点**落正字修掉（搜索/替换串全由码点数组构造，脚本正文不含任何 CJK）；`fix-chao.mjs` 的 LOOKALIKES 改为**空集并写明双理由**（旧码点是错的；且台账从本批起要**引用坏字形本身作证据**，自动替换会把证据改成正字）。**这一型的新知识：错字探针自己的码点也可以是错的 —— “报 0”有两种成因：没有错字，或没找对错字** |
| 4 | 两版 `scan-typo.mjs` 逻辑坏（`indexOf` 只报首处；过滤条件反了导致「合计 0」假绿） | 读数与目测不符（报 0 但屏上有） | 重写为计数 + 逐行扫描。**这一型就是 AGENTS.md 战役条款说的「引擎整条是空的却报出好分数」**，与 §14.7 附行 B 的 T5 初版同族 |
| 5 | 工单件一处替换失败：original_text 把锚句起手记错了（凭记忆而不凭实文本） | SearchReplace 当场拒绝 | 改锚到**句末完整一句**后成功。与本件 §14.6 那条「original_text 必须含定位锚的完整一句」同型再犯 ⇒ 本批才知道自己为何会再犯：**上一批把纪律写进了台账，但这一批动手时没重读那一条** |
| 6 | 一次 partial-success 的 diff 回显严重乱码，一度被读成「文件坏了」 | 用 Grep 复核文件本体 ⇒ 完好 | 定性为**显示层伪影**。登记一条：工具回显与文件本体是两个证据面，冲突时以**可复跑的只读命令**为准 |
| 7 | G6 total 从 139 推到 142，**只确证了其中一条新增边** | gates4 复跑 + `probe-g6list.mjs` 逐条列边 | 如实登记「未逐条归因」（行 ⑦ 备注）。⚠ 本行自身又是一次「因果句只跑了一半」：写了 +3 但没拿到三条坐标 |
| 8 | 本节 §15.7 的体量表写下即漂（取证件 1470 当时是对的，本节继续写就推它） | 写完 §15.8 后重跑 `(Get-Content).Count` | 不删数、不遮行：按「本行写下时测得 X + 终值见 §15.9」登记（与 §14.7 体量行、工单件 §8.1 同口径） |
| 9 | `volume8.ps1` 表头字符串插值小瑕（渲染成 `docs/README.md[2]`） | 读数屏上有后缀而预期没有 | 不影响求和，**不修**（修它不改变任何判据读数），只在此登记免得后人当 bug 追 |
| 10 | **同一写入链路把 U+672A（未）换成 U+6728（木）**：本批 §15.9 那句「本节尚未落地」被写成了另一个字 | 按码点全库扫 U+6728，实取 **5 处**：4 处是 §12 / §14 / 本批对历史错字的**引用**（不动），**只有 1 处是本批新造的活错字** | 按码点修（`fix-e8.mjs` 第 1 条）。⇒ 这一条把 #1 的口径**升级**：变形不是某一个字的坑，是**写入链路上 CJK 单字的通用风险**；所以纪律不是「遇到那个字用占位」，而是「**任何被引用的单字都要按码点复核**」，且词表型复扫（T1）永远只能覆盖已入库的字型 |
| 11 | **占位符替换工具分不出“用这个词”与“提这个词”**：行 1 里那个包在反引号里的 token（它本身就是要被替换的串）被 `fix-chao.mjs` 一并换成了正字 ⇒ 那一格当场变成自指矛盾：句子要求「写占位」，而占位的位置上站着的正是正字本身 | 写完 §15.10 后按码点回扫全节，发现该格内多出一个孤立正字 | 把那一格改成**描述 token 而不是示例 token**（行 1 末句即是），并因此在本节**不写出该 token 的字面形** —— 写一次就吃一次。登记口径：**任何自动替换型工具都要先问“本轮里有没有引用自身的场合”**（与本件 §14.7 附行 B 的 T3、L1355 的 T2 同一族：判据的散文与判据的对象共用形状） |
| 12 | **一支只读探针自己死循环，写出 300MB**：`cp-neighbours.mjs` 首版把未命中当 0 处理 —— JS 里 `indexOf(target, -1)` 既不「从尾部找」也不「报找不到」，它被钳回 0 ⇒ 循环永从行首重数，而它当时正被重定向进文件 | 命令挂了不返回 + 重定向文件长度在涨 | 进程强停、输出就地截断（`Clear-Content`；**DeleteFile 有 20MB 上限，这类文件只能用流式命令处理**），探针改成 `let at = indexOf(target); while (at >= 0) { …; at = indexOf(target, at + 1) }` 后才取到数（**本行写下前已实跑复证**：修好的探针对本件报出 `TOTAL 48` / `13 followed by an ASCII space`，行 13 那组数就是它报的，不是回忆）。⇒ 这一型的新知识：**危害不取决于它改不改被测物，取决于它输出到哪里**；「只读」不是安全属性，重定向才是。另一条通用坑：`indexOf` 的负数 fromIndex 被钳为 0，循环退出条件必须写在取得的那个值上 | 
| 13 | **非重叠匹配把第二个空格藏了**：`scan-space.mjs` 用「CJK + 空格 + CJK」的 /g 扫，对「不 + 动词 + 数」那一型只报出前一段（吃掉一个匹配后起点落在第二个空格上，不满足首字符条件）⇒ 第一次「清完」之后屏上仍剩带空格的坏形 | 清完再跑**修好的** `cp-neighbours.mjs` 按码点查该字右侧邻接（2026-10-31 实跑）：本件该字 **48** 处、右侧紧跟 ASCII 空格 **13** 处 ⇒ 逐条分型 = **9 处是占位符替换留下的残影**（左邻是 U+4E0D、右邻第一个字符是汉字），**4 处是合法形状**（左邻 U+7167 后接反引号 / U+5B57 后接拉丁词 / U+300C 后接加号 / U+5B9E 后接表格分隔符） | 第二轮只清那 9 处（规则把「左邻必须是 U+4E0D、右邻必须是汉字」写死在码点上 ⇒ 合法那 4 处天然不在射程内），复扫 `residual=0`（同一支探针、同一份文件：该字仍 **48** 处，但右侧带空格的只剩 **2** 处 —— 就是上面分型里 U+7167 与 U+5B57 那两条合法形状，说明规则只吃掉了 9 处残影没误伤射程外的东西）。**口径：任何扫形状的正则探针，命中数要先问它允不允许重叠**，否则「清干净了」是探针盲区给的假绿。⚠ **反向的那一条同样登记：不得把「CJK + 空格 + CJK」一律清掉** —— 门禁输出原文里那个空格是脚本拼接出来的（已核到 `check-tokens.mjs` L206–207 的模板串），清掉就是篡改逐字实抄。⚠ **同一支探针扫另四份文档（本轮实取）**：工单件 11 / 视觉件 13 / docs 索引 9 / web 索引 5 处该字，右侧带空格的只有视觉件 **1** 处且是合法形状（左邻 U+7167 后接反引号）⇒ 这一型残影**只落在本件**，不是全库问题 |
| 14 | **首轮体量行把合项当分项写**：那行括号里四个加数和与脚本报出的 total 不等（117 是两份 diff 的和，不是其中一份） | 末轮复算加和（只有把分项与总分同时抄在一行里，才会算出这个不等） | 订正已追加在 §15.9 首轮那行之后（原句不遮 —— 要看得出错在哪一步，得留着错的那一句）。⇒ 可复用的写法：**登记分解数时把加和式一并写出来**，下轮只需重算，不需回查脚本输出 |
| 15 | **把没跑过的数当陈述写进台账**：行 13 那一格当时写的是「实取三处」，而那个数是凭印象给的 —— 修好的探针在那一刻为止**一次都没成功跑通过**（它刚因行 12 死循环被强停） | 收尾轮重读自己写的行，发现「三处」背后没原始读数；当场实跑：该字 48 处 / 右侧带空格 13 处 / 其中残影 9 处 ⇒ 「三处」是错的 | 行 13 已换成实跑的 48/13/9，并在行 12 补「写下前已实跑复证」那一句。⚠ **本行是本批最重的一条**：它与「拿没跑过的数说我过了」是同一种错，只是方向相反（一个是吹成功，一个是吹取证）；区别仅在于本批在**入库前**发现了它 ⇒ 所以下轮读到本节里任何一个「实取」，先看它能不能对上 §15.9 某一轮的读数表，对不上就当未证实处理 |
| 16 | **台账引用错形，就把台账自己推进命中面**：两个读数因引用而涨 —— T1 从 5 到 **7**（新增的两条全在 L1595，那是末轮那一格里对两个错形的引用）、U+6728 从 5 到 **7**（多出的两处是末轮那一格与收尾轮 T1 那一格各自对自己的引用） | 收尾轮复跑 `typo-scan.ps1` 与 `fix-e8b.mjs --check`，两个数都比上一轮大 ⇒ 逐条定位新增行的来源，全是引用而非活错字 | **不删引用、不降读数以“修绿”**：引用错形本身就是这一型的证据（AGENTS.md 红线的另一副面孔是为过测试改测试）。登记口径：**词表型探针的基线会因引用上移而永久上移**，所以它的价值在「哪一条是活的」而不是「总数能不能回到低位」；后人拿 T1 做趋势判断时，先看命中行是不是 `「」` 里的引用 |
| 17 | **写入链路的第三个实例**：行 16 里一个双字词的第二字被写成了 **U+5024**（日文新字体形），而正字是 **U+503C**；同一个词的第一字 U+4EF7 是好的 ⇒ 它不是“整个词写错”，是**单字级替换**，所以人读一遍发现不了 | 落笔后按码点复扫自己刚写的三格（行 15/16 与新写的收口段）：`cp-locate.mjs 5024` 实取 **1 处** L1638，`cp-locate.mjs 4fa1` 实取 **0 处** | 进 `fix-e8b.mjs` 的 **文件域内规则表**（readings.md 专用：U+5024 → U+503C），与行 14 的 U+62C4 同批落正字，复扫归零。⇒ 这一条把行 10 那句「任何被引用的单字都要按码点复核」从口径**坐实成三个实例**：U+6284→U+62C4、U+672A→U+6728、U+503C→U+5024 —— 三个不同的字、同一类变形。⚠ **本行故意不示例 U+62C4 与 U+5024 这两个坏字形**（只写码点）—— 它们背后各挂着一条正在跑的文件域替换规则：行 11 已经量过 —— 一台按码点做替换的工具**分不出“用这个词”与“提这个词”**，把坏字形写进正文就等于给它标下一个待替换目标。另外登记一条可复跑的偏门检法：**扫自己新写的字不要只扫错字表（T1 只覆盖已入库字型），要扫自己刚贴过的那几个码点**。⚠ **登记完本行后又当场撞见第四个实例**：§15.12 那一段里一个双字词的第二字被写成 **U+6791**（正字 U+679C），`cp-locate.mjs 6791` 实取 **1 处** ⇒ 同批进规则表并归零。⇒ 上面那句「坐实成三个实例」在下一轮读时已经是**四个**（四个不同的字、同一类变形）；这就是行 16 那一型的现发生版本，不再另开行 |
| 18 | **同类错误又犯了一次（表格列数）**：给行 17 追加内容时把新文本开成了**第五格**，而本表只有四列 ⇒ 那一行当场破表 | 不是靠门禁：落笔后看替换回显时发现多了一个分隔符（门禁里能拦住它的是 `typo-scan.ps1` 的 T4，本轮跑在修之后 ⇒ **T4=0 是修完的读数，不是未犯过的读数** —— 两者不能混为一谈） | 合并回第四格（把那个多出来的列分隔符改成句号），复跑 T4=0。⇒ 本行的价值在**重复率而不只在处置**：同一个型（表头四列 / 数据行五列）在 §14.6・§14.8 行 21 已被登记过一次，本批又犯 ⇒ 当时的处置（「补表格形状检查」）只拦得住门禁面，拦不住我动手时不重读登记的那一条（与行 5 同根）。可复用的写法：**追加表格内容时先数目标表的列数再动笔**，而不是写完靠 T4 接住 |
| 19 | **新写的一行把 T2 从 18 推到 19**：web/README.md L144（本批那条入库陈述）里把一个**目录相对**路径包进了反引号，而 T2 的存在性检查按**仓库根**解析 ⇒ 报成 MISSING | 入库轮跑 `typo-scan.ps1` 与收尾轮对照：差值只有一条，逐条比两份命中清单才定位到那一行 | **不改**，理由是**改的代价大于它的害**：那串路径指向的文件真实存在、读者不会被误导（同文件 L20 那串没包反引号、L40 给的是根相对的完整命令），而修它要动**已入库的刀① 文件** —— 把刀① 的文件塞进刀③，会让工单件 §8.1 那条「文档轨豁免只覆盖那四份」的口径当场变形。⇒ 登记口径新增一条：**目录相对书写的路径一律不包反引号**（在本批的口径里，反引号等于承诺「按仓库根可解析」）；PR-0 的在册欠项补「web/ 内路径书写口径统一」。⚠ 这一型与行 16 同族（都是自己的新增文字推漂命中面）但**方向不同**：行 16 推的是错字词表，本行推的是存在性检查 —— 说明「自己会推漂的不只有字数」 |

### 15.11 附行：本批新建的取证 harness（不抄总数，总数以命令为准）

取法：`Get-ChildItem .tmp-scratch/ap-visual -File | Sort-Object CreationTime`（本行不抄支数，理由同 §14.7 附行 A 头句 —— 本批已经两次被自己新加的文件推漂那个数）。本批新增：**probe-r1.mjs**（§15.5 反证探针）、**volume8.ps1**（三刀体量现取）、**fix-chao.mjs**（码点级字符修正）、**scan-typo.mjs**（错字码点复扫，Node 旁路 PowerShell）、**probe-g6list.mjs**（逐条列引用边）。收尾轮又补四支：**scan-space.mjs**（只读扫「CJK + 空格 + CJK」形状，本批实取 27 处）、**fix-e8b.mjs**（码点级修正体例，`--check` 只审计 / `--fix` 才写，脚本正文不含任何 CJK）、**cp-locate.mjs**（按码点定位某个字、以码点序列打印邻接）、**cp-neighbours.mjs**（某个字全部出现的左右邻 + 计数，首版死循环见行 12）。全部住 gitignored，**不入库也不计刀**。⚠ 取法随动一条（本批收尾轮起生效）：**门禁输出改为落盘再读**（命令尾部 `> .tmp-scratch/ap-visual/e8-*.txt` 之后 `Get-Content` 读），起因是 PowerShell 的管道与控制台会在中文输出里**插入原文并不存在的空格**（行 13 那一型就是这么被误读的）；凡读到「像空格残影」的东西，一律先回文件本体按码点复核再落笔。⚠ 下游引用一律**指向本行而不抄支数**。

### 15.12 分支与三刀提交（方案 A 的兑现位 —— 未落地前本节不算已执行）

拍板内容（工单件 §8.1 分支项 (a)）：本地 `git checkout -b feat/web-visual-poc d140f91f`，按三刀提交；**不 push / 不碰 main / 不 force / 不解禁公开镜像 `github-legacy`**；合入 main 仍须用户显式批示（(b) 是 D2）。

**状态（2026-10-31 落定）**：刀①② 已提交（rev 与时刻见下表），刀③ = 本件自身 ⇒ 标题那句「未落地前本节不算已执行」对**本表的 ①② 两行已翻篇**，对「合入 main」仍未落地（那是 D2，不属本批授权）。

| 刀 | 包含文件 | 提交 rev | 提交时刻 | 该刀的 G1（后端 diff） |
|---|---|---|---|---|
| ① | 样式三件 + `web/README.md` | `2d6fe991` | 2026-10-31T22:31:10+08:00 | **lines=0** |
| ② | 两个宿主页 + `web/scripts/check-tokens.mjs` | `2c13b001` | 2026-10-31T22:31:18+08:00 | **lines=0** |
| ③ | 四份文档（本件 / 视觉件 / 工单件 / 顶层索引） | **本行写不了自己的 rev**（取法：提交后 `git log --oneline -3`，它就是那一行） | 提交前一轮读数见下段 | lines=0（与下段同轮取） |

**执行事实（2026-10-31 落定，逐条可复跑）**：
1. **分支**：`git checkout -b feat/web-visual-poc` 跑在 HEAD 上，而当时 HEAD 逐字等于 `d140f91f` ⇒ 与拍板原文「切点 `d140f91f`」等价（没走显式切点参数，但结果相同 —— 这一点要这样记，不能读成「拍板被简化了」）。现分支名 `feat/web-visual-poc`，现 HEAD `2c13b001`（刀②；刀③ 提交后就是那一行的值）。
2. **逐刀 G1 取法**（不是 gates4 那一条 working-tree 版，而是 commit 对 commit）：`git diff --name-only d140f91f <rev> -- applications packages scripts tests eval deploy Makefile pyproject.toml`，两刀都报 **空输出**（lines=0）⇒ “不碰后端一个字节”从本批开始是**入库后的可复跑事实**，不再只是工作区里的承诺。
3. **未做的动作（逐项点名，不得默认省略）**：未 push（且本轮仍没拿到远端读数 —— `git ls-remote --heads company` 那一条 rc=128 的在册欠项与本批同态）、未碰 `main`、未 `--force`、未解禁公开镜像 `github-legacy`、未删任何分支。⇒ 合入 main 仍是 **D2 待用户显式批示**，本地三刀不等于合入。
4. **提交后读数**（刀①② 已入库、刀③ 提交前取的那一轮，就是 §15.9 末段那条**入库轮**；命令逐字同 §15.9）：G0 = `2c13b001` / feat/web-visual-poc；G1 working-tree 版 **lines=0**；G2 非 docs 条目 **lines=0**（原 7 条 `?? web/…` 已因跟踪而消失，这正是下面那三条自指边界里第 ② 条预言的现形）；G3 True；G4・G5 rc=0；G6 **142 / 69 / 5**（BAD 五条同旧集）；G7 **8 / 9 / 11**；G8 四份全 0；`check-tokens.mjs` rc=0（定义/引用各 91、事件 12 / 字段 30）；`mutate-v1.mjs` 16/16 + 终态 rc=0；两支镜像树探针 existsSync=false；`typo-scan.ps1` T1=**9** / T2=**19** / T3=0 / T4=0 / T5=0（16 标签；两个数各自的增量定性在 §15.9 入库轮与行 19）；`volume8.ps1` 刀① 852 / 刀② 669 / 刀③ **2240**（视觉件 436 + 取证件 1679 + 两份 diff 共 125）・total **3761**（加和式：852 + 669 + 2240 = 3761）。
5. **⚠ 本段自己的自指边界**：第 4 条那组数是在本段落定**之后**跑的（填数不增行 ⇒ 重跑不会因本段而漂），但填进第 4 条那几个数位的那些值本身不在「跑的当时」的文本里；而 G6 / 本件行数 / 体量三类只要后续再写一个字就会漂 ⇒ **引用前按 §15.9 首句那组命令重取**，不得拿本段当现值。刀③ 提交后的 G0 / G2 属**下一批取证的第一轮**，不补写在本件里（那会形成“为追平读数而反复改自己”的链）。

⚠ **三条自指边界先写在这里，免后人拿本表当已完成陈述**：① 刀③ 包含登记本表的这一件 ⇒ **它自己的 rev 无法写在自己正文里**（取法：提交后 `git log --oneline -3`；本节只回填 ①② 两个 rev 与三条 G1）；② 提交后 G0 / G2 两项读数会当场变化（分支名不再是 feat/nl2sql-ttl-and-006-slim，G2 的 7 条 `?? web/…` 会因已跟踪而消失）⇒ 那些属于**提交后新一轮取证**，不改 §15.9 的首轮读数；③ 本节落地前，§15.1 末行那句「(a) 已批」只是拍板事实，不是执行事实；工单件 §8.1 分支项那句「没落到那一节之前本行不算已执行」以本表填完为准。

---

## 16. 第九批（2026-11-01）：一条欠项的前置问题被分面定死，顺手撞见一架量具随入库自己失效

**定位：** 单点收口批。做的是一件事 —— 把 `web/README.md` 那条在册欠项「根 README 的目录表里没有 `web/` 行」收掉，并**先**把它的前置问题（防漂移门禁到底认不认这种路径形状）用只读探针定死。附带产出三条：一架量具的口径缺陷（16.3）、一条流程事实（16.1 头两段）、一处差点写进台账的推测（16.6 行 1）。

**授权来源（一句话，不美化）：** 用户 2026-11-01 的原话要求「按上一轮给出的建议继续执行……不要把任何待拍板项当作已批准……若我说的『建议』指向不明，请先向我确认是哪一份建议，不要直接动手」。而上一轮结尾给的是 **A / B 二选一**（A 走 PR-0 那批文档随动 / B 是分支模型与合入的 D2）⇒ 判为**指向不明** ⇒ 本轮**先只做只读取证**（16.2 那支探针），再用选项卡请用户点定。用户点选 **A1**：补根 README 那一行 + 本地第四刀，**仍不 push / 不碰 main**；登记位置点选 **新开本节**。⇒ 本节射程 = A1，射程外一条未做，逐项点名在 16.1 末行。

**读数绑定 rev：** `d8cfecc3`（分支 `feat/web-visual-poc`，即刀③）。后端目录（applications / packages / scripts / tests / eval / deploy / Makefile / pyproject.toml）对该 rev 的 diff 在本批每一轮都是 **0 行**（G1，逐轮读数见 16.4）。

**取数时刻：** 2026-11-01，逐表标注。⚠ 老规矩不变：本件行数、体量、引用边三类只当**本轮量级**用，引用前按表头命令重取。

**前置（字段 5）：** Node v24.12.0；只读探针走 `uv run --no-sync python`，用门禁自带的**测试缝隙**（`base=` 与 `tracked=` 两个注入参数）在 gitignored 的 temp 副本上试算 ⇒ 对仓库文档**零写入**，跑完 rmtree。⚠ 本批新建的第二架 harness 是 PowerShell 脚本，`-File` 直跑会被执行策略挡（16.6 行 2），可用式子写在 16.7。

### 16.1 射程表（A1 逐条 ↔ 落地件）

| # | 建议项 | 本轮动作 | 落地件（指本节小节号，不抄路径清单） |
|---|---|---|---|
| 1 | 先定死前置问题：门禁认不认 `web/` 这种形状 | 做，只读 | 16.2 |
| 2 | 根 README 目录结构段补一行 | 做 | 根 `README.md` 的目录结构段，+1 行 |
| 3 | `web/README.md` 两处随动（两个挡路理由改「已定死」+ 欠项状态） | 做 | 该文件第二节那条、末节欠项行 |
| 4 | 新开本节登记 | 做 | 本节 |
| 5 | 定稿轮全套门禁 + 码点复扫 | 做 | 16.4 定稿轮那一列 |
| 6 | 本地第四刀提交 | 做 | 16.5 |
| — | `make ci-web`（= PR-0 开工授权）/ `web/` 内路径书写口径统一（A3）/ 分支模型 (b) / 合入 main / 解禁公开镜像 / AGENTS.md 目录表补行 | **一条未做** | 前五项是你点名列出的「不得当作已批准」项；最后一项超出 A1 射程，已就地登记为未随动（见 `web/README.md` 第二节那条末尾的 ⚠） |

⚠ **这一行的价值在过程而不只在结果**：如果本轮按「用户说了继续」直接动手，最容易越权的就是把 A1 与 A2 混着做（两支都碰文档、看起来像同一批）。分面定死之后才做的写，与先写了再补取证，是两种不同的批次 —— 本节是前者的形状。

### 16.2 前置问题定死：三条存在性面各自认不认 `web/`（实取，探针见 16.7）

问题原文（欠项挂了四批的那句）：「根 README 里加 `web/` 这一行，防漂移门禁会不会红？」—— 更准的问法是：**它会红，还是根本看不见？** 两个答案对后续动作的含义完全相反：会红 = 需要改门禁；看不见 = 加进去也不会提供任何保护，只是给人看的。

| 面 | 门禁里的检查 | 对 `web/` 的行为（2026-11-01 实取） | 该怎么读这句 |
|---|---|---|---|
| 文件引用面 | `check_doc_file_refs` | 前缀白名单是九个顶层目录的固定元组，**不含 `web/`** ⇒ 对 `web/`、`web/README.md`、`web/scripts/check-tokens.mjs` 三个候选**全部判 False**（控制候选 `docs/README.md` 判 True）；且该函数对**无扩展名**的串（目录引用）另有一条直接判 False 的分支 | 根 README 那一行**不红、但也校不到** ⇒ 绝不能读成「已通过校验」，只能读成「在射程外」 |
| 表格首列面 | `check_agents_md_paths` | 只扫 AGENTS.md 形如首列带反引号路径的表格行；候选行 regex 命中 group = `web/`，含 `/` 即进入存在性检查 ⇒ **会校到**；对当前清单判存在（目录由 files 派生） | 这一面加 `web/` 行**能过，而且过了是有意义的**（它确实在校验）—— 本批未动它，见 16.1 末行 |
| 架构目录面 | `check_architecture_paths` | 只扫 ARCHITECTURE.md 以 `/` 结尾的反引串与代码块内 top-level 目录行；试算报 **0 错** | 本批没动 ARCHITECTURE.md，这一面只是顺带确认「加行不会从这一面红」 |
| 存在性判据 | `TrackedIndex` | 基准 = `git ls-files`，实取 file count **1340**；`web/`、`web/README.md`、`web/scripts` 判 True，编的 web/nope（故意不包反引号，理由见本节行 9）判 False | 「目录已入库」这件事在这架门禁里就是**清单里有没有**，与本机文件系统无关（AGENTS.md 那条 2026-10-04 的坑同源） |
| **控制组** | 同上，但把清单里的 `web/` 剔掉再跑 | 当场报出 **1 条**：AGENTS.md 第 49 行「路径不存在 `web/`」 | ⇒ **这条校验不是空转**：同一份试算输入，把真相源抽掉它就红。新门禁的非空转反证按 evidence-format §4 要求就是这个形状 |
| 基线 | 三面在**当前树**（含本轮新写那一行）上跑 | **0 错** | 与 G4 rc=0 同轮取 ⇒ 那一行加进去之后门禁仍绿，是**实跑结果**不是推定 |

⇒ **分面结论（比「会不会红」更有用的那句）**：这条欠项的阻塞理由从「写进去必红」订正为「**写进去在校验面上是沉默的**」。所以根 README 那一行的价值定位是**给人看的导航**，不是给门禁的断言；真正的门禁面在 AGENTS.md 表格首列 —— 那才是补一行能换来保护的地方，也是本批按射程未动的那一处。

⚠ **不抄数形状**：本表不写「共几面 / 几条命中」的总数，逐面读数就是上面那张表；引用前重跑 16.7 那条探针命令（它幂等、零写入、末尾自删 temp）。

### 16.3 量具口径缺陷：`volume8.ps1` 对**已提交的刀**自己归零（发现 → 复跑 → 换量法）

**现象：** 第九批首轮（HEAD 已是刀③、工作区干净）跑体量那架，报出 刀① 852 / 刀② 669 / **刀③ diff 合计 = 0** / 刀③ 2115 / total 3636 —— 而第八批入库轮报的是 刀③ **2240** / total **3761**。**看起来像「产品退步了 125 行」**。

**定性（不是产品变化，是量具自己失效）：** 那架脚本对「被改的文件」用 `git diff --numstat`（**工作区 vs HEAD**），对新文件退化成全文行数。⇒ 一个文件一旦提交，它在工作区 diff 里就是 0 —— **量具的口径跟着「入库」这个动作自己塌掉**，塌的方式是**报小**而不是报错，所以它不会通知你。第八批那次 2240 之所以是好的，纯粹因为当时刀③ 还没提交。

**换量法（已提交对象的正确量法 = commit 对 commit）：** `git show --numstat <rev>` 逐刀求加和，本批新建 `volgit9.ps1` 承载它（见 16.7）。2026-11-01 实取：**2d6fe991 files=4 add+del=852 / 2c13b001 files=3 add+del=669 / d8cfecc3 files=4 add+del=2240 / total add+del = 3761** —— ⚠ 与第八批入库轮那组数**逐字同值**，这正是这次复跑的价值：它把入库轮那组「只能当时读」的工作区快照**升格成了可复跑的事实**（后人不需要工作区状态就能核对，`--numstat` 只看 commit）。

⇒ 登记两条可复用口径：① **「改文件的量法随提交动作失效」是通用坑**，任何「diff 工作区」型体量统计都必须配一支 commit 型旁路；② **当两个相邻批次的同一项数不等时，先怀疑量具，再怀疑产品** —— 本批如果直接写「刀③ 从 2240 降到 2115」就把量具故障记成了产品退步，后人会去找一个不存在的改动。

⚠ `volume8.ps1` **本批不修**：它对「本轮未提交的刀」仍然正确（刀④ 的量还是要用它现取），修它属于口径改造不是缺陷修复；改成两式并报（工作区式 + commit 式）记为 PR-0 欠项，与 16.2 那两处并列。

### 16.4 本批读数（首轮 = 工作区干净时；定稿轮 = 三处文字改完、刀④ 提交前）

取法：`powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/gates4.ps1`（八道一并购）+ 单独跑 `check-tokens.mjs` / `mutate-v1.mjs` / 两支镜像树探针 / `typo-scan.ps1` / 两架体量。**输出全部落盘再读**（第八批收尾轮起的纪律），逐份读档名不进台账、只指本节小节号。⚠ 定稿轮那一列写的时候是占位符 ⇒ **填数不增行**，填完必须复跑一遍证明逐字同值，否则本列不算实测。

| 项 | 首轮（HEAD `d8cfecc3`・工作区干净） | **定稿轮（刀④ 提交前）** |
|---|---|---|
| G0 / G1 / G2 / G3 | `d8cfecc3` / feat/web-visual-poc・lines=0・lines=0・True | G0 同值・G1 **lines=0**（本轮唯一动的 POC 侧代码零行）・G2 **lines=2**（就是 ` M README.md` 与 ` M web/README.md` 那两条，本件自己的 ` M` 因路径含 docs/ 不入这一面）・G3 True |
| G4 / G5 | rc=0 / rc=0 | **rc=0 / rc=0** |
| G6 引用边 | 142 / 69 / 5（BAD 五条同旧集） | **143** / **69** / **5**（BAD 五条同旧集）——⚠ 那 +1 是本节 16.2 表格里引用的控制候选（一个确实存在的 docs 索引路径）：它存在 ⇒ 不新增 BAD、不新增 unique（同一个串已在集内），只新增一条边 |
| G7 提及数 | 8 / 9 / 11 | **8 / 9 / 11** |
| G8 表格完整性 | 四份全 0 | **四份全 0**（本节新开三张表 + 自犯表过形状检查） |
| `check-tokens.mjs` | rc=0（定义/引用各 91、事件 12 / 字段 30、三组字典 12/12・30/30・30/30） | rc=**0**・定义/引用各 **91**・余同首轮 |
| `mutate-v1.mjs` | 反证格 16/16 有效 + 全撤销后终态 rc=0 | **16**/16 + 终态 rc=**0** |
| 两支镜像树探针 | `probe-throw2` 基线 rc=0・逐口 4/4 成立・误报 0 条・existsSync=false；`probe-r1` 四口 rc=1・误报行 12・30・26・34（派生集补齐后降到 17・13）・existsSync=false | throw2 基线 rc=0・逐口 **4**/4・误报 **0** 条・existsSync=**false**；r1 自证三格同首轮（return null 两口・拆跳过后未变异 rc=0 跳过行 0）・四口误报键名仍 12・30・26・34・existsSync=**false** |
| `typo-scan.ps1` | T1=9 / T2=19 / T3=0 / T4=0 / T5=0（16 标签） | T1=**9**（本轮新文字零新增命中，没拿引用去推基线）/ T2=**19** / T3=**0** / T4=**0** / T5=**0**。⚠ T2 这一格背后有一次**先涨后回落**：中途实取为 **20**（行 9 那一处），拆掉反引号后回到 19 ⇒ 登记的是**修完的终值**，20 不是未修而是修前读数（与 §15.10 行 18 的 T4 同口径：两者不能混为一谈） |
| 体量（工作区式） | 刀① 852 / 刀② 669 / **刀③ diff 合计 = 0**（16.3 那处故障）/ total 3636 | 刀④ diff 合计 **127**（add 123 / del 4，逐档：根 README +1、`web/README.md` +4/-4、本件 +115、工单件 +3）；同一架量具对刀③ 报出的仍是 **2233 / total 3754** —— 那个数**不得**当刀④ 的体量用（它就是 16.3 那处故障的本轮现形） |
| 体量（commit 式・16.3 换的量法） | 852 / 669 / 2240・total 3761 | 三刀同值复跑 = **852 / 669 / 2240・total 3761**（逐字同首轮；刀④ 提交后另加一行 rev，取法见 16.5） |
| 本件行数 | 1679 | **1794**（= 1679 + 115，与上面那行 diff 的 +115 对得上；填数不增行 ⇒ 填完复跑仍是这个数，那个反证在下一行末） |

⇒ 首轮这整列是**落盘读数**（每条都对得上 `.tmp-scratch/ap-visual/e9a-*` 那七份档），不是从第八批台账里搬来的；定稿轮那一列填完之后，本表才是「刀④ 提交前」的完整快照。⚠ **填数后的同轮复跑（2026-11-01，同一组命令逐字重跑）**：八道门禁与形状扫描**逐字同值**（G1 0 / G2 2 / G4・G5 rc=0 / G6 143・69・5 / G7 8・9・11 / G8 全 0 / T1=9・T2=19・T3-5=0 / 本件 1794）⇒ 「填数不增行」在本批**第二次**拿到实证（第一次在 §15.9 入库轮末段），而这第二次特别有用：本列有 **十九个**填位，只要有一个把数填成了字形相近的错字，就会在形状扫描里留下痕迹（T3/T4 那两道），全部同值就是它真的只改了数。

⚠ **追加轮（§16.6 行 11–12 与 16.7 那名落地之后重跑，2026-11-01）**：上面「定稿轮」那一列**不改写**（它是那一刻的实测，本行只登记其后的漂移，同 §15.12 那条「历史读数不追改」的口径）—— 本件行数 1794 → **1799**；刀④ 工作区式 diff 合计 127 → **132**（add **128** / del **4**，其中本件那一项 +115 → +120）；G6 **143 / 69 / 5**（BAD 五条同旧集）；G8 四份 hits 全 **0**；`typo-scan` T1=**9** / T2=**19** / T3=**0** / T4=**0** / T5=**0**；码点复扫 U+5854 五份合计 **0**（且 U+584C 8 与 3、U+6C89 2 与 2、U+6728 7、U+62C4 1 五项与上一轮**逐项同值** ⇒ 新写的那三行没引入一个码点级变形）、`fix-e8b --check` TOTAL fixable **0**。⚠ 这一段同样是**先占位后填数** ⇒ 填完必须再跑一轮证明逐字同值才算实测（本批第三次用这条反证），那一轮的读数取法与本行表头同一条命令。

### 16.5 刀④（本地第四刀 —— 超出第八批「三刀」形状的那一刀）

**形状：** 一支刀 = 四个文件：根 `README.md`（+1 行）、`web/README.md`（两处随动）、本件（§16 全节）、工单件（§13.4 第九批那一段）。G1 必 0 行 —— 四个文件全不在后端目录里。

**为什么它需要单独拍板（D1，不是 D0）：** 第八批批的是「三刀」，刀③ 的边界就是那四份文档；再切一刀就多了一个提交、一条 rev、一份需要与前一批对齐的分支形状。可逆（本地未 push，`git reset --soft` 即可并回），但**改动形状**而不是改动一个字 ⇒ 按决策边界表归 D1，已问过、已点定。

**自指边界（这一刀同 §15.12 那条，且更短）：** 刀④ 包含登记刀④ 自己的这一件 ⇒ **本行写不了自己的 rev**。取法：提交后 `git log --oneline -4` 第一行就是它；体量用 16.3 那条 commit 式现取（`powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/volgit9.ps1 -Revs <那四个 rev>`）。⚠ 提交后的 G0 / G2 属**第十批首轮**，不回填在本节里。

**未做的动作（逐项点名，不得默认省略）：** 未 push、未碰 `main`、未 `--force`、未解禁公开镜像、未删任何分支、未建 `make ci-web`、未动 AGENTS.md 与 ARCHITECTURE.md。⇒ 分支仍只住在本地，合入 main 仍是 D2 待你显式批示。

### 16.6 本批自犯表

| # | 自犯 | 怎么发现的 | 处置与可复跑证据 |
|---|---|---|---|
| 1 | **把推测当陈述写**：本轮动手前我对定稿轮的预期是「G2 非 docs 条目会从 0 变 **1**」—— 那个 1 是只数了一个文件的想当然，而 G2 的过滤器是「行里不含 docs/」，**根 README.md 自己也在这一面** | 落笔前先重读了 gates4 里那行过滤器（重读**代码**而不是重读我自己的记忆） | 该数不写成 1，改占位符由实取填（**实取 = 2**，见 16.4 定稿轮那一格）。⚠ **本行可核对的部分不是那句预期**（它只存在于我上一轮的计划文字里，未落进任何文件 —— 刚才已拿会话记录核过：那句未入库，所以将来者无法复跑它），可核对的是那行过滤器的形状与那个实取值 2。⇒ 第八批行 15（「把没跑过的数当陈述」）的**同型**，差别只在这一次被动手前的复读接住了 |
| 2 | 新建的 PowerShell harness 用 `-File` 直跑被**执行策略**挡下（rc=1），且失败信息**写进了重定向文件而不是回显**；另有一条语言层错：`foreach (…) {…} \| Out-File` 报「empty pipe element」（foreach **语句**不能直接进管道，得先落成脚本或包成 `$(…)`） | 第一次跑 rc=1；读落盘的档才看到原因（如果只看 rc 与回显会当成脚本没输出） | 可用式子固化为 `-NoProfile -ExecutionPolicy Bypass -File`，已写进 16.4 表头与 16.7 的取法句 —— 后人照抄这一条即可。⇒ 与 §15.10 行 12 同族但**方向相反**：那次是「只读探针输出到哪里才危险」，这次是「失败读数住在文件里，所以『落盘再读』连报错都能接住」 |
| 3 | **一次中文模式报 0、差点被读成「那句话没说过」**：为了核行 1 那句预期有没有落进过会话记录，我用了 `Select-String -Pattern '从 0 变' -CaseSensitive`，得 **hits=0** —— 而 PS 5.1 不指定 `-Encoding` 读 UTF-8 中文时，这个 0 有两种成因（真无 / 没读对） | 不当结论用：改走 ripgrep 旁路重查两个词，再拿一个**已知在档里存在**的中文词做控制组（它命中 ⇒ 解码链路是通的，于是 hits=0 升为「确实未入库」这一种成因） | 结论按**控制组成立的那一侧**写（就是行 1 里那句「刚才已拿会话记录核过」）。⇒ 这一条是 §15.10 行 3 那句「报 0 有两种成因」在**中文编码**上的新实例（前面那个实例是码点错字），后人拿任何一次「搜不到」当陈述前先问控制组 | 
| 4 | **A1 的射程里暴露出一条未登记的欠项**（中途发现的新的问题，不是错字）：探针报「AGENTS.md 表格首列面**会校到** `web/`」—— 而我们四批来担心的只是根 README 那一面（校不到的那一面），所以「补了 README 行」很容易被后人读成「门禁面上已覆盖」 | 写 16.2 时逐面核对探针输出，发现两个面的答案相反（一个沉默、一个在校） | 就地双点登记：`web/README.md` 第二节那条末尾的 ⚠（人读面）+ 本节 16.1 末行（射程面）；**不动 AGENTS.md**（超出 A1）。⇒ 可复用口径：**登记一条欠项时要同时登记「它的保护在哪一面」**，否则收了 A 面的欠项会被当成 B 面也收了 |
| 5 | **本表差点自己造假一次**：行 4 这一格最初填的是一条「本批把 T1 命中行用无 `-CaseSensitive` 的 `Select-String` 抓错了」—— 而那次坑是**第八批收尾轮**踩的，本批**一次都没跑过那条命令** | 落笔后自查本表：逐行问「本批真的做过这件事吗，能不能对上 16.4 或 16.7 的某一条读数」—— 行 4 对不上 ⇒ 当场判为错归因；**顺手还抽核了自己引的那条出处**（拿关键词回查 §15.10 与 §15.11）→ **查不到** ⇒ 连「它已登记在第八批表里」也是我自己给的假出处 | 删除那条、换上本批实际发生的行 3 那一格（控制组那一跑是 2026-11-01 本轮命令）。⚠ **这一行必须留在表里**：它是「自犯表自己虚报一条 + 引用一条不存在的登记」的双层实例，比台账里其余四条都重 —— 自犯表是错闭环的地基，它一旦可以拿邻批的坑凑数，整张表就退化成写作模板。**另记一条属实信息（不记成本批自犯）**：那型 PowerShell 默认不区分大小写的坑确实在第八批发生过，但**台账里至今没有它的条目**（§15.11 当时登记的是另一件事：落盘再读的起因是中文输出里被插入空格）⇒ 它属于「当时没入册的历史动作」，本行就是它的迟登记位，不要再回到 §15.10 去补写（那会把历史批次的表改成事后凑齐的形状）。与 §15.10 行 15（把没跑过的数当陈述）同族，方向相同、对象不同：那次污染的是读数，这次污染的是**认错记录与它的出处** |
| 6 | **写入链路的第五与第六个实例（且第一个是“删”不是“换”）**：本批在工单件新写的三行里，一个字的正字 U+584C 被写成了形近 U+5854（1 处），而另一个双字词的**首字 U+6C89 直接没落上去**（不是形变，是**脱落**：三字序列只剩两字） | 不是靠目测也不是靠 T1（词表永远只覆盖已入库的字型）：新写的四份文件跑 `cp-sweep9.ps1` 按码点计数，U+5854 报 **1**（预期 0）而 U+584C 报 **2**（预期 3）；两个数一起指向同一句。另拿 U+6C89 计数在工单件也是 **1**，但坐标在它那边的 **L509**（早于本批的文字）⇒ 确认本批那一处是脱落不是改写 | 由本批新建的 `.tmp-scratch/ap-visual/fix-e9.mjs`（**规则全部由码点数组构造、正文不含 CJK**）一次修完并复扫归零：两条规则各 matches=1 → --fix → matches=0。⇒ 这一行把 §15.10 行 17 那句「四个不同的字、同一类变形」**扩容成两型**：前面五个实例都是**形近替换**，本批第一个是**单字脱落** —— 所以「按码点复核」不能只校「有没有错字」，还要校**预期字数**（只数字形会漏掉脱落这一型）。⚠ 本行不示例那两个坏字形，只写码点（理由同 §15.10 行 11 / 行 17：自动替换型工具分不出“用这个词”与“提这个词”） |
| 7 | 本批新建的计数探针**标签不可分**：它用 `Split-Path -Leaf` 报文件名，而根 `README.md` 与 `web\README.md` **同名** ⇒ 两行输出长得一样、数字不同（一个 3 一个 5），读数时无法分辨那是哪一份 | 落盘档里连续两行同名不同值，一眼就看不过去 | 改成报**相对路径全名**（已改，本批后续读数就是改后取的）。⇒ 可复用口径：**任何逐文件汇总的探针，标签必须是全路径而不是叶名** —— 与本件 §15.10 行 8、行 14 同族（登记格式本身要能容下歧义），只是这一型长在探针输出上 |
| 8 | **自己刚立的「不抄总数」当场被自己破**：16.7 首句写成「本批新建两支」，而我登记完那句之后又新建了三支（体量、计数扫描、坐标转储）⇒ 那句总数从写下那一刻起就是错的 | 补 16.7 名清单时看到自己写的「两支」与手里要列的五支不等 | 改成**按用途列名而不写总数**，与本件 §14.7 附行 A、§15.11 同口径。⇒ 这一行的价值在于它把那条口径的成因**坐实了一次**：总数不是被后人改坏的，是被**我自己后来的动作**改坏的 —— 所以下次想在散文里报一个「共几支 / 共几道」之前，先问它会不会在本轮内自涨 |
| 9 | **上一轮刚立的反引号口径，本轮就违反了一次**：16.2 表里那个**故意不存在**的控制组路径被我包进了反引号 ⇒ 形状扫描 T2 从 19 推到 **20**（那条检查按仓库根解析路径，解不到就报 MISSING） | 定稿轮跑 `typo-scan.ps1` 与首轮逐项比：差的只有一条，逐条定位到本节那一行 | 拆掉那对反引号（已改，改后复跑 T2 回到 **19**）。⇒ 这一条比 §15.10 行 19 那条走一步：那条是**目录相对**路径错用了仓库根口径，本条是**根本不存在的假路径**（它是控制组的输入，不是引用）—— 所以口径要补成：**反引号 = 承诺「按仓库根能解到」，所以只有真实存在的对象能包；故意举的反例、占位、待填路径一律用普通文本** |
| 10 | 在 PowerShell 里拿 `-Command "…$_…"` 嵌一段管道：`$_` 被**外层会话先展开成空串**传下去，于是变成 `.Line : The term '.Line' is not recognized`（一条看起来像「缺 cmdlet」的错，其实是引号问题） | 同一条命令里那几段不依赖 `$_` 的输出正常、只有带 `$_` 的三段落空 ⇒ 不是路径也不是门禁问题 | 改用 **Grep 工具直接读落盘档**（本批定稿轮那几道读数就是这么取的）；另记一条口径：**凡需要管道内逐行取字段，一律写进只读脚本文件跑，不用外层 `-Command` 内联** —— 与行 2 同族（都是「外壳把引号与变量先吃了一句」），但那一行是执行策略，这一行是变量展开 |
| 11 | **取证链路自己骗了取证**（本批新发现，既不是错字也不是量具）：同一份落盘档里混了**两种编码** —— 前半用 PS 5.1 的 `>` 写（默认 UTF-16LE，头两字节 `ff fe`），后半用 `Out-File -Encoding utf8 -Append` 追加（UTF-8、无 BOM）⇒ 读档的一方按**文件头 BOM** 判编码，于是追加那半被当作 UTF-16 逐对解，整段变成「UTF-8 字节被按 UTF-16 解出来的那种假 CJK」 | 一眼可判它不是数据坏：那一段的内容**全是 ASCII**（路径与十六进制码点标签），纯 ASCII 段不可能自己变成中文。定死用一支 ASCII 探针打四份落盘档的头 8 字节，三种形状各自对上：乱码档 `ff fe`（两种编码混在一档）、正常档 `ef bb bf`（`Out-File -Encoding utf8` 独写）、无 BOM 档 `55 2b`（探针自己写的） | 口径固化两条：① **一份取证档只允许一种写入方式**，跨轮追加要么统一走 `Out-File -Encoding utf8`，要么让探针**自己写字节**（本批为此给计数探针加了 `--out`，见 16.7）；② 「读起来正常」**不能**证明编码对 —— 同一轮里另一份用 `>` 写的档因为**载荷恰好全 ASCII** 而看不出问题，判据只能是头字节。⇒ 与本节行 2 同族而**方向相反**：那次是失败读数住在文件里、文件救了取证，这次是文件骗了取证 |
| 12 | **差点把坏通道读成坏数据，进而去「修」一份本来干净的文件**：那段乱码刚出现时，我手上的结论候选是「commit message 里有异常字符」—— 若采纳，就会去改那份从头到尾没错过一个字的 msg 档，把真缺陷（取证通道）登记成假缺陷（被检对象），两头都错 | 换一条**不共用编码层**的通道重量一次（探针 `--out` 自己写字节），五份被检对象的码点计数与 16.4 定稿轮已记的同项读数**逐字同值**（U+5854 全 0、U+584C 在两份文档各为 8 与 3、U+6C89 为 2 与 2、U+6728 为 7）⇒ 目标文件没动过，动的是通道 | ⇒ 可复用口径：**报「发现坏数据」之前，先证明是数据坏还是通道坏** —— 办法是换一条与被怀疑通道不共用解码层的路径重量，两次不等而目标未被写入 ⇒ 判通道。这与 16.3 那条「相邻批次同一项数不等时先怀疑量具」是同一个动作，只是对象从**数**换到**字节**：量具故障那一型在编码层有它的对应物 |
| 13 | **搜索工具面读到的是滞后快照，不是当前文件字节**（行 12 那条口径本批当场复用了一次，而且这次方向相反）：为核「工单件那三行到底在不在」，拿 IDE 的搜索工具对工单件跑一个中文模式与一个纯 ASCII 的日期模式，**两边都报 0**；而同一工具对取证件跑同一个中文模式报 **3 条命中** —— 第一反应候选是「那三行没写进去」，第二反应候选是「本窗口刚写进去的那四个字也没看见？」（它确实也报 0） | 控制组不靠猜：`git diff` 读的是**工作区活字节**，落盘档里那三行加号全在（含两处 ASCII 日期）⇒ **文件里有、工具看不见**；而同一工具在另一份文件上的命中又排除了「中文模式本身就是原因」 | ⇒ 「报 0 的成因」清单添第三条（前两条见行 3：真无 / 解码错；本条是**索引滞后**）：**任何「某内容不在某文件里」的陈述必须用读活字节的通道反证一次**（`git diff` / 直读文件 / 探针自写档），搜索面的 0 只能当线索不能当结论。⚠ 本行自己的代价就是它把上面那个数又推漂了一次（落地后本件行数与刀④ 体量再涨，见下一段）—— 与行 8 同型，所以不新建口径，只把那条口径再证一次：**别在散文里写会被自己后续动作改坏的数** |
| 14 | **登记一条漂移的那句话，自己把那个数改了**（本批第三种自指，也是前两种的合体）：再追加轮要解释「U+6284 从 54 涨到 55」的成因，我在句子里把那个字**原字引出来**写了一遍 ⇒ 下一次重跑它变成 **56**：一个用来解释计数的句子，成了计数的新增项 | 同一组命令重跑后比对五份落盘档的 SHA256，得 **2 条差异且全部落在同一份码点计数档**（其余四档全等 —— 形状类读数确实没被“填数”这件事改动）；差异那一档逐项一看，动的正是 U+6284 | 处置**不是**把数改回去，而是把**引用方式**改掉：按 §15.10 行 11 那条既有口径「提及某个字就写它的码点、不示例其字形」重写那一格，于是它不再自涨；本批后续凡要提一个被计数的字，一律写 U+XXXX。⇒ 本行与行 8（散文里写总数被自己的动作推漂）、行 13（登记本身推漂被登记的数）同族，但更狠一层：**它污染的是一次测量的自变量**，只有改引用方式能终止，靠再跑一轮去追数是追不完的 |

⚠ **再追加轮（§16.6 行 13・行 14 依次落地后同命令重跑，2026-11-01）**：上面 §16.4 那条「追加轮」的数**不改写**（它也是那一刻的实测，本段只登记其后的漂移）—— 本件行数 1799 → **1805**；刀④ 工作区式 diff 合计 132 → **138**（add **134** / del **4**，本件那一项 +120 → +126）；G6 **143 / 69 / 5**（BAD 五条同旧集）；G8 四份 hits 全 **0**；`typo-scan` T1=**9** / T2=**19** / T3・T4・T5=**0**；码点复扫 U+5854 五份合计 **0**、TOTAL fixable **0**；U+6284 在本件 54 → **53**（不是形变：本行与 16.7 各有一句把那个动词换成了「写」，净减一；中间它还漂到 55 与 56 两次，成因分别就是行 13 与行 14）。⚠ **档位哈希自证（行 11 换的判据第一次上机）**：占位态与填数态两次重跑比对五份落盘档 SHA256，**第一次**得 diff **2** 条（全在同一份码点计数档，就是行 14 那一格）；把引用改成码点、行 14 入册之后再比，得 diff **0** 条；那个数填完后再跑一次比对，仍为同值。

### 16.7 附行：本批新建 / 换用的 harness（不抄总数，总数以命令为准）

本批新建的 harness 全在 gitignored 目录、**不入库也不计刀**（按用途列名、**不写总数** —— 理由见本节节末行 8：总数会被我自己随后的新增动作当场改坏）：**probe-docsync-webrow.py**（16.2 的只读探针，正文全 ASCII、走门禁自带测试缝隙、末尾 rmtree）、**volgit9.ps1**（16.3 的 commit 式体量，默认三支已提交 rev，可传 `-Revs`）、**cp-sweep9.ps1**（本批新建的码点计数扫描，标签用相对全名）、**fix-e9.mjs**（码点级修正，`--fix` 才写、规则全由码点数组构造）、**temp-dump-line9.mjs**（把某一行的指定区间按码点打出来，用来分辨「形近替换」与「单字脱落」）、**cp-count-any.mjs**（任意码点计数，`--out` 让探针**自己写字节、控制台完全不参与** —— 就是本节行 11 的处置件）、**e9h-round.ps1**（一轮把八道门禁 + 形状扫描 + 体量 + 码点全部重取，**每份落盘档只用一种写入方式**）、**e9i-verify.ps1**（同一组命令重跑两次、比对五份落盘档的 SHA256 —— 行 11 那条新口径的执行件）。取法逐字：

```bash
uv run --no-sync python .tmp-scratch/ap-visual/probe-docsync-webrow.py
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/volgit9.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/cp-sweep9.ps1
node .tmp-scratch/ap-visual/cp-count-any.mjs --out <落盘档> <hex,hex,...> <文件...>
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e9h-round.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e9i-verify.ps1
```

上面这些 PowerShell 行的**可用调用式都得带 `-NoProfile -ExecutionPolicy Bypass`**（`-File` 不带它会被挡，见本节行 2；而本行原本写的是「两支 harness 的调用式就是上面那两行」—— 那又是一个被自己后续动作改坏的总数，与本节行 8 同型，已改成不限数的写法）。换用（非新建）一支：`volume8.ps1` 继续负责「本轮未提交的刀」（刀④ 用它），但**不得**再拿它回答「某支已提交的刀多大」—— 那个问题归 volgit9（理由与实取见 16.3）。⚠ 与第八批同规：下游引用一律**指向本行而不写支数**，取法用 `Get-ChildItem .tmp-scratch/ap-visual -File | Sort-Object CreationTime`。

---

## 17. 第十批（2026-11-01）：一条空输出逼出第三次通道自证，一条挂了五批的假路径被定为「从未入库」

**定位：** 收口批，三件半事 —— ① 兑现 §16.5 末尾那条自指边界（刀④ 提交后的 G0 / G2 属「下一批首轮」）；② 把 §16.6 行 11–14 之外本批新撞到的 harness 坑入册，并顺手修掉其中一支量具；③ 半件：把本件 L627 那条挂了五批的账面欠项并入本批收口（17.6）。

**授权来源（一句话，不美化）：** 用户 2026-11-01 经选项卡两项点定 —— 新坑处置 = **甲**（开本节登记 + 修 volgit9，即批准多一个入库提交）；历史欠项 = **并进本批一起处理**。上一轮「继续」我只当它授权只读取证 ⇒ 本批的写动作全部来自这两项点定，射程外一条未做（逐项点名在 17.8）。

**读数绑定 rev：** `e9564eec`（刀④，分支 `feat/web-visual-poc`）。后端目录（applications / packages / scripts / tests / eval / deploy / Makefile / pyproject.toml）对该 rev 的 diff 本批每一轮 **0 行**，且这一条不再是单通道读数（17.2 三条互不通电）。

**取数时刻：** 2026-11-01。⚠ 老规矩：本件行数、体量、引用边三类只当**本轮量级**，引用前按对应命令重取。

### 17.1 首轮全套读数（在入库后的 rev 上重取，逐项对照 §16.6 终值）

取法：`powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e9l-round.ps1`（一轮八件，每份落盘档只用一种写入方式 —— §16.6 行 11 的口径）。

| 项 | 首轮读数 | 与 §16.6 登记终值的关系 |
|---|---|---|
| G0 / G1 / G2 / G3 | e9564eec / feat/web-visual-poc・lines=0・lines=0・True | G2 从刀④ 提交前的 **2** 回到 **0**：那两条 ` M` 因入库而消失，正是 §15.12 自指边界 ② 预言的现形 |
| G4 / G5 | rc=0 / rc=0 | G4 那句「文档同步校验通过（0 警告）」现在跑在**含 web/ 行的根 README** 上 ⇒ 刀④ 没把防漂移门禁弄红，是实跑不是推定 |
| G6 引用边 | 143 / 69 / 5 | 与 §16.6 再追加轮**逐字同值**（这三个数各自的意思见 17.4） |
| G7 提及数 | 8 / 9 / 11 | 同值 |
| G8 表格完整性 | 四份全 0 | 同值（§17 自己新开那五张表也过这一道） |
| `check-tokens.mjs` | 定义/引用各 91・派生集 事件 12 / 字段 30・三组字典 12/12・30/30・30/30 | 同值（本批零 POC 代码、零样式值） |
| `mutate-v1.mjs` | 反证格 16/16 + 全撤销后终态 rc=0 | 同值 |
| 两支镜像树探针 | throw2 基线 rc=0・逐口 4/4・误报 0 条・existsSync=false；r1 自证三格同首轮・四口误报键名 12・30・26・34・existsSync=false | 同值 |
| `typo-scan.ps1` | T1=9 / T2=19 / T3=0 / T4=0 / T5=0（16 标签） | 同值 ⚠ 但本批 17.6 收了那条假路径之后 T2 会**降一项**，降后的实取在 17.7 |
| 体量（commit 式） | 852 / 669 / 2240 / 138・total 3899 | 刀④ 那一行由 17.5 行 1 修好的量具**一次调用**取回，与上一批「单 rev 逐次调用 + 手工加和」的结果同值 |

⇒ 一句话读数：**刀④ 入库没有推动本 POC 任何一个门禁值**（除 G2 那两条按预期消失的 ` M`）。这一列看着像「什么都没变」，它的价值恰恰在此：它把 §16 那批的终值从**工作区快照**升格成**入库 rev 上的可复跑事实** —— 与 §16.3 那次「复跑同值 ⇒ 快照升格」是同一个动作，作用在下一批的起点上。

### 17.2 「空输出」不能自己作证：同一判据的第三条通道

**现象：** 首轮想取「逐刀后端不变量」，落盘档是一份**只有空行的文件**。

**为什么本批把它当成一条独立证据而不是一个小疑点：** §16.6 行 11–14 刚立的口径说的就是这件事 —— 一个没量的通道报 0，和一个量了且确实为 0 的通道，**在文件里长得一模一样**；而 §16.3 那次量具故障也是同一形状（塌的方式是报小不是报错，所以它不会通知你）。所以本批拒绝拿那个空档写「G1=0」。

| 通道 | 命令形状 | 实取读数 |
|---|---|---|
| ① 正控制（同一命令**去掉**路径过滤） | `git diff --name-only <rev>~1 <rev>` | 逐刀 **4 / 3 / 4 / 4** ⇒ 这架命令**会**报出行，于是它报的后端 0 是量出来的不是漏出来的 |
| ② 逐刀后端面 | 同一命令带八个后端路径 | 逐刀 **0 / 0 / 0 / 0**；累计 d140f91f 到 HEAD 也 **0** |
| ③ 第三条通道（不共用 PowerShell 的编码层） | node 内 `execFileSync('git', …)` 取数后 `fs.writeFileSync` 自写字节 | backend-files=**0** / all-files=**12**；该落盘档头 8 字节 `62 61 63 6b 65 6e 64 2d`（**不是** `ff fe`）⇒ §16.6 行 11 的头字节判据在**第三个**写入方上再次成立 |

**顺带对掉了一对看起来像不一致的数：** 逐刀文件数相加 **15**，而累计只 **12**。对账结果 = 三个文件被两刀各碰一次（`web/README.md`、本件、工单件）：flat-sum=15 / unique-flat=12 / cum=12。⇒ 这不是漂移，是「逐刀口径」与「累计口径」的固有差；但**不去对这一对数，它就会在下一次被人当成量具坏了** —— 与 §16.3 同型而方向相反：那次是相邻两批的数不等，这次是同一批内两个口径的数不等。

### 17.3 远端读数欠项的成因被改定：rc=128 是网络不可达，不是命令用错

`git ls-remote --heads company` 本批实取 **rc=128**，stderr 给的是 ssh 连接超时（内网 git 主机 port 30001，主机名按公开镜像口径不落在库里）。⇒ 那条从 §14.7 起连报三批「没拿到远端读数」的欠项，成因从「命令可能没跑对」**改定为「环境不可达」**。同轮 `git remote -v` 取到 4 行：`company` 的 fetch / push 各一条，`github-legacy` 的 push 那条写着 DISABLED-no-push；**无 `origin`** —— AGENTS.md 分支卫生 §3 那句「照抄 origin 只会报 No such remote」在本仓是实事实。⚠ 这条改定**不解除**「远端恒 2 分支」那一格的未复核状态：网络通了仍要复取。

### 17.4 引用边基线更新：139 → 143，而 BAD 五条同旧集

§12.2 与 §13 两处登记的基线是 total=139 / unique=69 / unresolved=5；本批首轮 **143 / 69 / 5**。三个数各自的意思不同，不能笼统写成「涨了四条」：

- **total 139 → 143** = 刀③ 入库那四份文档与刀④ 新写的文字里多了四条 docs/ 开头的反引号引用 ⇒ 账面上的**新增边**，不是断链。
- **unique 69 不变** = 那四条边指向的目标都已在集合内 ⇒ 没有新的被引对象。
- **unresolved 5 不变且同旧集** = 三条 ADR 无扩展名短写（真名带后缀，短写在正文里是人读的）+ 一条故意改坏的夹具（plan-web-visual-design-2026-10-30.mX，它是 §12.2 那次非空转反证的输入，删了等于把反证拆掉）+ 一条假路径（本批 17.6 收的就是它，但**只收了 docs 索引那一处**，台账自己还留着另一处 —— 理由与复审触发条件在 17.6 第 4 条）。

⇒ 所以「G6 里有个 5」不得被后人读成「还有五条待修」：三条是人读的短写、一条是有意保留的反证夹具、一条是本批收了**一半**的假路径。

⚠ **同一次收口在两个扫描面上读数不同（本批实测，不是推定）**：T2 从 **19 → 18**（降一项），而 G6 的 unresolved **5 → 5**（不降）。成因不在被改的对象，在两架工具的**射程不同**：G6 跨四份文件数 docs/ 开头的反引串 ⇒ 台账自己在 §12.2 里留着的那处反引号仍计入；T2 按文件去重后拿 Test-Path 解 ⇒ docs 索引那一处一消失就少一条。⇒ 该型与 §16.2 那条同源：**登记一条欠项时要同时登记「哪一面会读到它」**，否则「收了」会被下一个拿 G6 读数的人读成「根本没收」。

### 17.5 本批自犯 / 坑表

| # | 自犯或坑 | 怎么发现的 | 处置与可复跑证据 |
|---|---|---|---|
| 1 | **量具的第二个静默零**：`powershell -File x.ps1 -Revs a,b,c,d` 这一式里 PowerShell 5.1 **不把逗号串绑成数组**，整串成为一个元素 ⇒ 脚本拿它当**一支** rev 去量，落盘档于是只有**一行**（那一行的 rev 名就是整串逗号），报 files=0 add+del=0、total 也是 0，而 **rc 仍是 0**，git 那句 unknown revision 只落在 stderr | 首轮体量只拿到一行全 0，而同一批手工单 rev 逐次调用报的是 852 / 669 / 2240 / 138 ⇒ 两次数不等，先怀疑量具（§16.3 那条口径第二次生效，第一次是 16.3 本身） | 按用户点定的**甲**就地修 volgit9（gitignored，不入库不计刀）：入参先按逗号再切一次；且**每支 rev 先过 `git rev-parse --verify`，解不到就打印 UNRESOLVED-REV 并 exit 1** —— 未量的东西不许打印 0。修后一次调用取回 852 / 669 / 2240 / 138・total **3899**・rc=0；**负控制**同架喂一支坏 rev：报 UNRESOLVED-REV + revs-measured=1 / revs-requested=2 + FAIL + **rc=1** ⇒ 那道新守卫**非空转** |
| 2 | **`$ErrorActionPreference='Stop'` 会把原生命令的 stderr 变成终止错误**：`git ls-remote` 那条经 `2>&1` 进管道后当场中断脚本，于是**记录 rc 的那一行根本没跑到** —— 首轮少取一条读数，且表因是「脚本 rc=1」而不是「这条命令 rc=128」 | 落盘档少一份，且脚本停止位置正好停在那一行上 | 该轮补跑改用 `Continue`，读数于是拿到（就是 17.3 那两组）。⚠ **不把 harness 里的 Stop 一并撤掉**：Stop 是有意装的（项目侧脚本写错要早断）。固化为一条口径：**承载原生命令的轮次用 Continue，承载项目脚本的轮次用 Stop** —— 这条区分是本轮撞出来才知道的，之前每一轮的注记里都没写 |
| 3 | **.NET API 的当前目录不跟随 `Set-Location`**：`[IO.File]::ReadAllBytes('相对名')` 按**进程** CWD（仓库根）解析，于是对着一份**确实已生成**的落盘档报 Could not find file，表观像「探针没写出来」 | 同一条命令里 `Test-Path` 说 True、`ReadAllBytes` 说找不到 ⇒ 两个答案相反，判为解析基准不同而不是文件问题 | 取字节一律改**绝对路径**（17.2 那组头字节就是这么取到的）。⇒ 与 §16.6 行 12 同一个动作：两个读数冲突时**先怀疑读法，再怀疑对象** |
| 4 | **行 13 那一型第二次现形**（不是新坑，是同坑复用）：为对齐工单件第九批那三行的格式，搜索工具对一个中文模式报 **0** —— 而那三行刚刚在刀④ 里入库 | 不当结论用：`git show` 限定那一份文件落盘再读，三行全在（含中文表头） | ⇒ §16.6 行 13 那条口径本批**从预测变成用过一次**。本节所有「某内容在不在」的判断一律走活字节面（`git show` / `git diff` / Select-String），搜索面的 0 只当线索 |
| 5 | 扫描工具里一条**永远进不去的分支**（本批顺手查出，不是本批造成的）：typo-scan 的 T2 段有一条「允许指向 gitignored 取证目录」的豁免（以 .tmp-scratch 开头则跳过），但它上游的过滤只放行七个顶层前缀打头的串 ⇒ **以 .tmp-scratch 开头的候选在上一层就被筛掉，这条豁免从未命中过** | 写 17.6 时为了决定新路径要不要包反引号，去读 T2 的过滤式才看见它 | **本批不删**（删它等于改动一件正在产出读数的工具，而它无害；本批已把这条写进 17.7 的读数来源注记）。登记为在册项：豁免分支与过滤面不匹配，要么放开过滤面、要么删豁免，随 PR-0 的口径批处理。⇒ 与 §15.10 那条「填错码点的形近清理集从未命中过」同型：**空转的修复比没有修复更糟**，因为它让人以为这件事已经处理了 |
| 6 | **在「修一处中文错字」这个动作里又写出五处中文错字**（三处在写 17.4 末段那一段时，两处在修这三处的同一轮）：先把「反引号」的第二个字写成了 U+5F13（正字 U+5F15），随后拿替换去修它，替换文本里又把「跨」写成了 U+8DF1（正字 U+8DE8），同一段又把「抓不到」的首字写成 U+62D3 不到（正字 U+6293）⇒ 三回形近替换，第二、第三回是**修复动作自己带进来的**；而随后修这三处的替换**又带出两回** —— 「口径」写成 U+52B2 径、「抓判断词」写成 U+62D3 判断词，**后者正是 §16.6 行 14 那个自指型的第三次现形：在登记该型的同一句话里复现该型** | **不是扫描接住的**：T1 词表只防本会话历史真踩过的型，码点复扫清单里也没有这几个字 —— 接住它的是**读工具回显的那段 diff**（替换报 success 之后返回的前后文） | 五处均按码点改回；本批定稿轮额外拿 U+5F13 / U+8DF1 / U+62D3 / U+52B2 四个码点在本页计数（实取在 17.7）。⚠ U+62D3 的计数**不等于本批新增**：坐标探针逐处核到 7 处全落在 §17 之前（L1344 三处、L1573 两处、L1595 一处、L1613 一处，其中六处是 §15.10 / §16.6 当年示例该型时留下的字形，第七处（L1344 末）是 U+62D3 + U+6251 组成的网络术语（正词，非错字；工单件 L481 那一处同理），按历史读数不追改的口径不动）⇒ 本批新增 0 处。另记一条：本行第一版把错字位置写成「末字」（实为第二个字），也是读自己回显的 diff 才发现 —— 读 diff 不只抓错字，也抓判断词。⇒ 可复用口径（这一条比 §16.6 行 6 再往前走一步）：**每次替换后必须读它回显的 diff，不能只看「编辑成功」**——行 6 那几个实例是形近替换 / 单字脱落**被码点扫描抓到**的，而本行这一型**扫描面根本抓不到**（字不在任何清单里），只有人读那一段才看得见 ⇒ **码点复扫是下限不是上限**；新踩到的型要进清单（下一批可把 U+5F13 / U+8DF1 / U+62D3 / U+52B2 归口到 T1 或扫描集，属工具改动，本批未动） |
| 7 | **填进台账的数被自己随后的编辑改掉了**（本批第四次反证抓到的）：把定稿轮读数填进 17.7 之后，为了说明「U+62D3 的第七处是正词不是错字」，在行 6 里写下了那个字的字形 ⇒ 该码点在本页从 7 变 **8**，而表里刚填进去的仍是 7 —— 写入值与实取值当场不一致（本行第一版自己又在同一句话里把这个字写错了一次，经上面那句同样的复跑接住） | 不是靠人眼：按纪律填数后同命令复跑两轮（七份档 SHA256 逐档同值），再**把复跑读数逐项对回表里写的数**，U+62D3 那一项对不上才发现 | 处置：那句改成按码点书写（U+62D3 + U+6251），复跑回到 7、与写入值一致。⇒ 新增一条口径：**两轮同值只证明测量可复现，不证明写入值等于测量值**；闭合需要第三步——把复跑读数逐项对回台账里写的数。证据：抓到时的读数快照 e11-08-caught-62d3-8.txt（count=8）与第一轮同值证明 e11-07b-first-proof.txt |
| 8 | **反证自己可以拿陈旧数据报绿**（本批最硬的一条，比行 7 严重）：为了把比对集从「七份产出 + 两份留档快照」收窄回七份，我把 harness 里的 `Get-FileHash` 通配改成带 `-Filter 'e11-0[0-6]*.txt'` —— PowerShell 的 `-Filter` 走 Win32 通配，**不支持字符区间**，于是匹配到 0 个文件，`Get-FileHash` 当场报 `Cannot bind argument to parameter 'Path' because it is null`，但脚本**接着拿上一轮留下的两份 hash 档比对**，照样打印 `RESULT: A == B` | 同轮输出里 `hash-lines = 10` 与句子里写的「七份」矛盾 ⇒ 去核选取式，才发现空集 + 陈旧档这两件事叠在一起 | 三处加固：① 跑前先删 hash 档（拿不到新档就不许有旧结论）；② 选取改 `-like 'e11-0[0-6]*'`（PS 通配支持区间）；③ **比对前断言集合大小恰为 7，不等于 7 就打印 FAIL 并退出 1** —— 前置条件不满足时拒给结论。修后正跑 `compared-files = 7`・`A == B`・rc=0；**负控制**把谓词放宽成 `-like 'e11-0[0-8]*'` 走同一条判据 ⇒ `widened-set-count=10` + `GUARD FIRED` ⇒ 新守卫非空转。⇒ 可复用口径：**任何「复跑同值」的反证，先要证明它读的是本轮新写的档**；比对集大小与措辞里的数量必须出自同一处断言，不能各写一遍（harness 在 gitignored 侧，不计刀） |

⚠ 本表与 §16.6 同口径：只登记本批真实发生、且能对上 17.1–17.7 某一条读数的条目；邻批的坑不许搬进来凑数（那条纪律的来历见 §16.6 行 5）。

### 17.6 挂了五批的假路径收口：docs/plans/README.md 从未进过版本控制

**欠项原文形状：** docs/README.md §6 那一条里有两处把它当文件引用（一处解释 71 → 82 的分母口径差，一处说「新增的 1 篇是它」）；本件 L627 自第十批起登记为「待你拍板」。

**先做定性（三支只读探针，读数全在落盘档）：**

| 问法 | 实取 | 含义 |
|---|---|---|
| tracked 清单里有没有它 | `git ls-files` 限定该路径 = **0 行** | 门禁的存在性判据里没有它 |
| 它**曾经**存在过吗 | `git log --all` 配 `--diff-filter=A` = **0**、`--diff-filter=D` = **0**、不带 filter 的总历史 = **0** | **不是「曾存在后被删」** ⇒ 那句不是历史读数，是假路径。这一条**决定处置方向**：历史读数只能订正追加，假路径可以就地改 |
| docs/plans 下真正的索引 README 在哪 | tracked 只有 `docs/plans/archive/README.md` **一篇**；本机 FS 同值 | 重算脚本排除的是**同目录顶层**那个文件名（脚本规则 1 按 name 排除），与 archive 子目录那篇不是同一个对象 |

**处置（三处，全部只动 docs 面）：**
1. 那两处反引号**拆掉** —— 依据是 §16.6 行 9 那条口径：反引号 = 承诺「按仓库根能解到」，只有真实存在的对象能包；故意举的反例与不存在的假路径一律用普通文本。
2. 就地补一句带日期的订正：写明它从未入库（上面那三条读数），并写明**「新增的 1 篇」到底指什么，现有证据无法复原** ⇒ 因此**不改写那两个历史数字**（71 → 82 与 29 → 28 那串原样保留），只收掉「会被后人当成真实路径」的形状。
3. 同一假路径在 `scripts/evidence/recount_plan_status_lines.py` 的 docstring 里也有一处 —— **本批不动**：`scripts/` 在后端目录内，「后端 diff 对 d140f91f 为 0 行」是本 POC 八批未破的硬判据。就地登记为在册欠项（随后端批处理），并把「为什么不顺手修」写在原处，免得后人以为是漏了。
4. **台账自己那一处（本页 §12.2 那行）本批也不拆** —— 这不是漏，是一笔有代价的选择：那处反引号是 §12.2 / §13 / §14 三处历史登记共同的证据形状（它们逐处写着「BAD 五条同旧集」），拆掉它 G6 会降到 4，但那三条登记的读数当场失去可核对性 —— 而它们正是本件引用边非空转的反证链本身。⇒ **登记口径：当收一条引用会碎另一批登记里的反证形状时，先保住反证，把收口停在能停的那一面。** ⚠ **复审触发条件（按分支卫生第 2 条，没条件的登记不许写）**：① 若未来某批愿意接受「BAD 四条」为新基线并**同时**在那三处历史登记里追加一句订正，那就拆；② 若该路径真的入库（有人创建了它），本行自动作废，G6 自行归零那一项。

⇒ 这条欠项**收的是「引用形状会骗人」这一面**；至于「§7 那串分母到底该不该含索引 README」，脚本口径早已把它钉死为**排除**（规则 1），本批未改任何计数。收口实取：T2 **19 → 18**，G6 unresolved **5 不动**（两面上读数不同的成因见 17.4 末段，台账内那处保留的理由与复审条件见上面第 4 条）。

### 17.7 本批读数（首轮 = 落地前・工作区干净；定稿轮 = 三个文件的文字改完、刀⑤ 提交前）

首轮取法逐字同 17.1 那一条（`e9l-round.ps1` + `gates4.ps1` + `e9n-round.ps1` + `cp-count-any.mjs`）；定稿轮一次成型走 `e11-round.ps1`（一支管八道门禁、typo-scan、体量、码点复扫、坐标复核、后端面三通道，共七份落盘档 e11-00…e11-06）。⚠ 定稿轮那一列**先占位后填数** ⇒ 填完必须同命令复跑证明逐字同值（本批第四次用这条反证），否则那列不算实测。【本批实做：占位轮取数 → 填数后同命令复跑两轮，七份落盘档 SHA256 逐档同值（`compared-files = 7`、rc=0、e11-07-twice.txt），再把复跑读数逐项对回本表——行 7 就是在这一项上抓到过一次不等（实取 8 vs 写入 7），改到逐项相等之后本句才成立】

| 项 | 首轮（HEAD e9564eec） | 定稿轮（刀⑤ 提交前） |
|---|---|---|
| G1 / G2 | 0 / 0 | 0 / 0（三份改动全在 docs 面，后端不变量未被本刀碰） |
| G4 / G5 | rc=0 / rc=0 | rc=0 / rc=0（G4 报「文档同步校验通过（0 警告）」、G5 All checks passed） |
| G6 引用边 | 143 / 69 / 5 | **144 / 69 / 5** —— total 比首轮多 1 而 unique 不动 ⇒ §17 新写的文字里多了一条 docs/ 开头的边，且它指向的目标已在集合内（新增边不是断链；本批未逐条定位到是哪个串，要定位就拿 gates4 的 G6 段打印 BAD 外的全量集）；unresolved **仍 5 不降**，与 17.4 末段那句「两面射程不同」一致 |
| G7 / G8 | 8 / 9 / 11 ・ 四份全 0 | **9 / 10 / 11** ・ 四份全 0 —— 前两项各 +1 来自 §17 正文自己多了提及，不是新引用关系 |
| `typo-scan.ps1` | T1=9 / T2=19 / T3=0 / T4=0 / T5=0 | **T1=9 / T2=18 / T3=0 / T4=0 / T5=0** —— T2 降的那一项就是 17.6 收掉的 docs 索引那处假路径 |
| 码点复扫 | U+5854 五份合计 0・TOTAL fixable 0 | U+5854 六份合计 **0**・TOTAL fixable **0**・U+5F13 **0**・U+8DF1 **0**・U+52B2 **0**・U+62D3 **7**（坐标探针逐处核到全在 §17 之前，本批新增 0） |
| 体量（工作区式） | 0（干净） | add **139** / del **1** / total **140**（本件 135/0・docs 索引 1/1・工单件 3/0） |
| 本件行数 | 1805 | **1940** |

### 17.8 刀⑤（本地第五刀）与未做的动作

**形状：** 一支刀 = 三个文件：docs/README.md（那两处反引号 + 一句订正）、本件（§17 全节）、工单件（§13.4 那张表补本批三行）。G1 必 0 行 —— 三个文件都不在后端目录里。
**为什么它需要单独拍板（D1，不是 D0）：** 第八批批的是三刀、第九批把形状扩到四刀；第五刀再扩一次 = 多一个提交、一条 rev、一份需要与前一批对齐的分支形状。可逆（本地未 push，`git reset --soft` 即可并回），但改的是**改动形状** ⇒ 归 D1，已问过、已由「甲」点定。
**自指边界（同 §16.5，一字未改地再适用一次）：** 刀⑤ 包含登记刀⑤ 自己的这一件 ⇒ **本行写不了自己的 rev**。取法：提交后 `git log --oneline -5` 第一行就是它；体量用修好的 commit 式量具现取（式子见 17.9 末行）。⚠ 提交后的 G0 / G2 属**第十一批首轮**，不回填在本节里。
**未做的动作（逐项点名，不得默认省略）：** 未 push、未碰 `main`、未 `--force`、未解禁公开镜像、未删任何分支、未建 `make ci-web`（PR-0 开工授权仍未给）、未动 AGENTS.md 与 ARCHITECTURE.md、未做 web/ 内路径书写口径统一（A3）、**未动 `scripts/` 里那处同名假路径**（后端不变量，理由写在 17.6 第 3 条）。⇒ 分支模型 (b)、合入 main、公开镜像解禁、后端联调开工**仍按未批准处理**。

### 17.9 附行：本批新建 / 换用的 harness（按用途列名，不写总数）

全部住在 gitignored 目录、**不入库也不计刀**（不写总数的理由见 §16.6 行 8）：**e9l-round.ps1**（17.1 那批首轮，每份档单一写入方式）、**e9n-round.ps1**（17.2 的正控制轮）、**e9o-round.ps1**（17.2 末段那次体量对账 + 历史欠项的活字节面复查）、**e9p-selfwrite.cjs**（17.2 第三条通道：node 自己写字节）、**e10-probe.ps1**（17.6 那三支定性探针）、**e11-round.ps1**（定稿轮一支管八道门禁 + typo-scan + 体量 + 码点复扫 + 坐标复核 + 后端面三通道）、**e11-twice.ps1**（17.5 行 7/8 那两次反证：同命令复跑两轮并按 SHA256 逐档比对，比对集大小不恰为 7 时拒给结论）。另有一组**未固化成文件**的补跑（17.5 行 2 的 `Continue` 那一轮、17.5 行 3 的头字节那次）—— 它们的读数在落盘档里，取法照 17.5 那格的描述现编即可。换用（非新建）：`gates4.ps1` 继续管八道门禁；**volgit9 按 17.5 行 1 修好**，现在可一次调用量多刀，且解不到 rev 会 rc=1 而不是打印 0。取法逐字：

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e9l-round.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e9n-round.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e9o-round.ps1
node .tmp-scratch/ap-visual/e9p-selfwrite.cjs
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e10-probe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e11-round.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/e11-twice.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .tmp-scratch/ap-visual/volgit9.ps1 -Revs 2d6fe991,2c13b001,d8cfecc3,e9564eec
```

⚠ 上面最后那一行**正是 17.5 行 1 那个坑的调用式**：修之前它把四支 rev 当成一支然后静默报 0，修之后它一次取回四行 —— 后人拿这一条当「怎么一次量多刀」的式子用，不必再逐支调用。



