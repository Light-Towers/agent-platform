#!/usr/bin/env node
/* ============================================================================
 * check-events.mjs — 事件契约门禁（工单件 §9.3 登记件 / §7 PR-1 判据）
 * 零依赖：只用 Node 内置 fs/path。挂 `make ci-web`，**不进 `make ci`**。
 *
 * 与 check-tokens.mjs 断言 6 的分工（不写清就会被读成「同一条查两遍」）：
 *   那件管**图例**（poc.html 的 EVENTS 与 events.ts 的 EVENT_LEGEND 两副本的 key 集与文案同值），
 *   本件管**处理链**（后端 Literal → serialize_stream_event 分支 → TS 联合 → sse.ts handler 分支
 *   → PR-2 的消费面：icons.ts 图标表 + events.css 的 accent 规则）。
 *   两者在「TS 联合 == 派生全集」这一格重合，重合的代价是一条判据可能在两处同时报红
 *   （读数重复），不是一处漏；删掉任一件都会留下一条无主判据。
 *
 * 本件全部断言是 readFileSync 文本/正则形状断言 ⇒ 属工单件 §10.5 已定性的**脆断言**，
 * 只锁结构不变量（分支齐不齐），**不锁行为**（分支跑得对不对）。行为的判据在
 * `web/scripts/verify-sse.mjs`（真 import 被测模块喂帧），两件互替不了：
 * 「handler 表里有一个叫 route 的键」与「route 帧进来会渲染成一行时间线」是两件事。
 *
 * ⚠ 本件不出现事件**条数**：期望集只从源派生。工单件 §12-#1 记的正是这个坑 —— 门禁一入库
 *   就带一个源码里凑不出来的常数，实现者只能二选一：把门禁写成永不可满足（红到被人关掉），
 *   或硬凑出多一类事件（假绿）。§12 反证表第 4 行的实取判据落在这里。
 *   下面那两组「白名单」同样不抄数：`CLIENT_ROW_KINDS` 从 `sse.ts` 的 `kind` 联合派生，
 *   存储白名单 `STORAGE_WL` 是**双向**的（列了却没用也算漂移），两条各有各的失败口。
 *
 * ⚠ §12-#2 那条后端侧断言的方向是**单向 ⊆**，不是双向相等：Literal 有项而 serialize 无分支 ⇒
 *   `serialize_stream_event` 返回 None **静默丢事件**（`:792` 自陈），运行期零症状，前端连
 *   「未处理的事件类型」都报不出来，因为它根本支不到 —— 这是唯一会"没症状"的方向。
 *   反方向（有分支但不在 Literal 里）是死代码而不是静默丢失，本件故意不管。
 *
 * 源读失败口径沿用 check-tokens.mjs 第八批 ① 的定论：读不到源 ⇒ `fail.push` + **跳过该项
 *   双向比较**。只把 throw 换成 fail.push 不够 —— 空集合进比较会被逐项报成「缺项/多项」，
 *   一条源坐标问题炸成整屏误报，反而把人往「字典写错了」的方向引。失败本身已计入 fail
 *   ⇒ rc 仍为 1，门禁不空转，也没有为了凑绿放宽断言。
 *
 * 形状耦合（写进代码的约定，不是隐形假设）：`sse.ts` 的 handler 表必须**一行一键**且值为
 *   以 `(s` 开头的箭头函数 —— 表体里嵌套的 `event:` / `kind:` / `text:` 键缩进是 6 空格、
 *   且后面不跟 `(s`，两个条件同时把它挡住。形状被改（比如换成方法简写）会读空 ⇒ 下面
 *   有专门的"一条都没读到"失败口，不会静默降级成"全绿"。
 * ==========================================================================*/
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/* 行尾归一：同 check-tokens.mjs —— Windows checkout 是 CRLF，锚点写 `\n` 会让同一份门禁
 * 在 LF 环境红。归一只消除行尾差异，不动任何声明内容。 */
const readText = (p) => readFileSync(p, 'utf8').replace(/\r\n/g, '\n');

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const ROOT = join(WEB, '..');
const fail = [];
const note = [];
const rd = (rel) => readText(join(ROOT, rel));
/* 两套基准必须分开：后端源按**仓库根**读（派生源住在仓库里，不在 `web/` 下），
 * TS 侧按 **`web/`** 读（与被测文件同基准）。混用会让一条路径写错变成 ENOENT 而不是判红。 */
const rdWeb = (rel) => readText(join(WEB, rel));

const PROTO = 'packages/agent-runtime/agent_runtime/planner/protocol.py';
const ROUTER = 'applications/agent_server/api/query_router.py';
const TS_EVENTS = 'src/api/events.ts';
const TS_SSE = 'src/api/sse.ts';
const TS_ICONS = 'src/components/icons.ts';
const CSS_EVENTS = 'src/styles/events.css';
const VUE_TIMELINE = 'src/components/Timeline.vue';

/* ---- 派生源 1：后端 `StreamEventType` Literal ---- */
const proto = rd(PROTO);
const literalBlock = proto.match(/StreamEventType\s*=\s*Literal\[(.*?)\]/s);
if (!literalBlock) fail.push(`读不到 StreamEventType Literal（${PROTO} 的派生源坐标变了，先核对再改门禁；后端侧与全集比较已跳过）`);
const LITERAL = literalBlock ? [...new Set([...literalBlock[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]))] : null;

/* ---- 派生源 2：`serialize_stream_event` 的分支集 ---- */
/* 函数体单独切：只从 `def serialize_stream_event` 起、到下一行退回列 0 为止。整文件扫会把
 * 别处的 `event.type ==` 也算进来（本仓现在没有，但那是"目前凑巧"，不是判据）。 */
const serializeBody = (() => {
  const lines = proto.split('\n');
  const start = lines.findIndex((l) => /^def serialize_stream_event\b/.test(l));
  if (start < 0) {
    fail.push(`读不到 def serialize_stream_event（${PROTO} 的函数坐标变了，先核对再改门禁；Literal ⊆ 分支集这条已跳过）`);
    return null;
  }
  const body = [];
  for (let i = start + 1; i < lines.length; i++) {
    if (/^\S/.test(lines[i]) && lines[i].trim() !== '') break;   // 退回列 0 ⇒ 函数结束
    body.push(lines[i]);
  }
  return body.join('\n');
})();
const BRANCHES = serializeBody === null
  ? null
  : [...new Set([...serializeBody.matchAll(/if\s+event\.type\s*==\s*"([a-z_]+)"/g)].map((m) => m[1]))];

/* §12-#2：Literal 有项而 serialize 无分支 ⇒ 静默丢事件。这一条**只有本件校**（后端那半以前没人管）。 */
if (LITERAL && BRANCHES) {
  const unhandled = LITERAL.filter((n) => !BRANCHES.includes(n));
  if (unhandled.length) {
    fail.push(`后端侧断言失败（§12-#2）：Literal 声明了但 serialize_stream_event 没有分支 ⇒ 运行期返回 None 静默丢事件：${unhandled.join(', ')}`);
  } else {
    note.push(`后端侧：Literal ${LITERAL.length} 项全部有 serialize 分支（分支 ${BRANCHES.length} 条）✅`);
  }
} else {
  note.push('后端侧：⚠ 跳过比较（Literal 或 serialize 函数体读不到，见上方失败行）');
}

/* ---- 派生源 3：实现里直接下发的字面量（_node_event + router 直发）---- */
/* 两种书写形态都要吃：字典里的 `"type": "x"` 与 kwargs 里的 `type="x"`。口径与
 * check-tokens.mjs 断言 6 同形 —— 两处若要改口径必须同批改，否则同一个"全集"会有两个数。 */
const emitted = new Set();
for (const text of [proto, rd(ROUTER)]) {
  for (const re of [/"type":\s*"([a-z_]+)"/g, /type="([a-z_]+)"/g]) {
    for (const m of text.matchAll(re)) emitted.add(m[1]);
  }
}
const EVENT_SET = LITERAL ? [...new Set([...LITERAL, ...emitted])].sort() : null;

/* ---- 被校物 1：events.ts 的 TS 联合 ---- */
const tsUnion = (() => {
  const lines = rdWeb(TS_EVENTS).split('\n');
  const start = lines.findIndex((l) => /^export type StreamEventType\s*=/.test(l));
  if (start < 0) {
    fail.push(`读不到 export type StreamEventType（${TS_EVENTS} 的坐标变了，先核对再改门禁；联合项比较已跳过）`);
    return null;
  }
  const out = [];
  for (let i = start + 1; i < lines.length; i++) {
    const m = lines[i].match(/^[ \t]*\|[ \t]*'([a-z_]+)'[ \t]*$/);
    if (!m) {
      if (out.length === 0) {
        fail.push(`${TS_EVENTS} 的 StreamEventType 下一行不是「| 'x'」形状（联合项读不到，双向比较已跳过）`);
        return null;
      }
      break;
    }
    out.push(m[1]);
  }
  return out.sort();
})();

/* ---- 被校物 2：sse.ts 的 handler 分支表键集 ---- */
const handlerKeys = (() => {
  const block = rdWeb(TS_SSE).match(/const EVENT_HANDLERS[^{]*\{([\s\S]*?)\n\}[ \t]*satisfies/);
  if (!block) {
    fail.push(`读不到 const EVENT_HANDLERS … } satisfies（${TS_SSE} 的表体坐标或 satisfies 尾形变了，先核对再改门禁；handler 侧比较已跳过）`);
    return null;
  }
  const out = [...block[1].matchAll(/^ {2}([a-z_][a-z0-9_]*)[ \t]*:[ \t]*\(s/gm)].map((m) => m[1]).sort();
  if (out.length === 0) {
    // 一条都没读到 ≠ 表是空的：更可能是形状换了。这里必须单独报，不能让它走到下面
    // 变成"12 条全缺项"——那会把一次坐标漂移伪装成一次内容缺失。
    fail.push(`${TS_SSE} 的 EVENT_HANDLERS 里一条 key 都没读到（表体形状与文件头声明的「一行一键 + 值以 (s 开头」不符，不是分支被删）`);
    return null;
  }
  return out;
})();

/* ---- 双向比较 ---- */
const diff = (a, b) => a.filter((x) => !b.includes(x));
const cmp = (label, mine, derived) => {
  if (!mine || !derived) {
    note.push(`${label}：⚠ 跳过比较（${!derived ? '派生源' : '被校侧'}读不到，见上方失败行）`);
    return;
  }
  const miss = diff(derived, mine);   // 源里有、代码里没有 ⇒ 会静默漏渲染
  const extra = diff(mine, derived);  // 代码里有、源已不产出 ⇒ 死分支
  if (miss.length) fail.push(`${label} 缺项（源产出但代码没接）：${miss.join(', ')}`);
  if (extra.length) fail.push(`${label} 多项（代码接了但源已不产出）：${extra.join(', ')}`);
  note.push(`${label}：代码 ${mine.length} / 派生 ${derived.length} ${miss.length + extra.length === 0 ? '✅' : '❌'}`);
};
cmp('TS 事件联合 ↔ 派生全集', tsUnion, EVENT_SET);
cmp('handler 分支 ↔ TS 事件联合', handlerKeys, tsUnion);

/* ================= 消费面三枚齿（PR-2 刀㊲）=================
 * 为什么要在这里加：后端加一类事件时，上面两条会让 handler 表与 TS 联合报红，但**渲染面**
 * 是第三种失败形状 —— `icons.ts` 的 `rowClassOf` 对没跟上的事件名**收敛到 `ev--unknown`**，
 * 症状是「这一行变成了未识别样式」而不是门禁红（静默降级，与 §12-#2 那一族同形）。
 * 三枚齿各自拦一种漂移：
 *   齿 A 图标表键集（缺 = 那一类没有图标）
 *   齿 B events.css 的 accent 规则（缺 = 拼出一个 CSS 里不存在的 class，那一行无声地没色）
 *   齿 C 凭据存储面（PR-2 新写了两个组件，工单件 §2.3 那条纪律自此才真的有人可违反）
 * 三者都是**双向**比较：只查缺项会漏掉「前端自己多接一类」（那是一枚无消费者的死 class/死图标）。 */

/* ---- 齿 0（前置）：客户端侧行种类从 `sse.ts` 的 kind 联合派生，不抄数 ----
 * `TimelineEntry.kind` 的三个值里，`'event'` 是**后端事件行**（它的 class 由事件名决定，
 * 不是一种额外种类），剩下两个才是客户端自造的 row kind ⇒ 去掉 'event' 后剩下的就是期望集补。
 * 读不到这一行 ⇒ fail + 跳过两处比较（口径同上：不把坐标问题报成内容缺失）。 */
const kindLine = rdWeb(TS_SSE).match(/readonly kind:\s*((?:'[a-z_]+'\s*\|?\s*)+)/);
const KIND_VALUES = kindLine ? [...kindLine[1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1]) : null;
if (KIND_VALUES === null) {
  fail.push(`读不到 TimelineEntry 的 readonly kind 联合（${TS_SSE} 的形状变了，先核对再改门禁；消费面两处比较已跳过）`);
}
const CLIENT_ROW_KINDS = KIND_VALUES ? KIND_VALUES.filter((k) => k !== 'event').sort() : null;
if (CLIENT_ROW_KINDS !== null && CLIENT_ROW_KINDS.length === 0) {
  fail.push(`${TS_SSE} 的 kind 联合里除了 'event' 一个客户端侧行种类都没有（期望集补为空，消费面两处比较已跳过）`);
}

/* 期望集 = 派生全集 ∪ 客户端侧行种类（两者都来自源，本件不写死任何一类名字）。 */
const CONSUME_SET = EVENT_SET && CLIENT_ROW_KINDS
  ? [...new Set([...EVENT_SET, ...CLIENT_ROW_KINDS])].sort()
  : null;

/* ---- 齿 A：icons.ts 的 ICON_PATHS 键集 ---- */
/* 形状耦合与 EVENT_HANDLERS 同形（一行一键、值为单引号字符串）；读空单独报，
 * 不让它渗到下面变成「全集 N 项全缺」。 */
const iconBlock = rdWeb(TS_ICONS).match(/export const ICON_PATHS[^{]*\{([\s\S]*?)\n\}/);
if (!iconBlock) {
  fail.push(`读不到 export const ICON_PATHS … }（${TS_ICONS} 的表体坐标变了，先核对再改门禁；图标侧比较已跳过）`);
}
const iconKeys = iconBlock
  ? [...iconBlock[1].matchAll(/^ {2}([a-z_][a-z0-9_]*)[ \t]*:[ \t]*'/gm)].map((m) => m[1]).sort()
  : null;
if (iconBlock && iconKeys && iconKeys.length === 0) {
  fail.push(`${TS_ICONS} 的 ICON_PATHS 里一条键都没读到（表体形状与「一行一键 + 值为单引号串」不符，不是图标被删）`);
}
/* 每一枚 path 得是非空串：`x: ''` 能过键集比较，屏上却是一个 invisible 图标（又一个静默形状）。
 * 正则只取引号之间的内容，所以这一格能判空而不能判“画得对不对”（后者属 V4 实拍）。 */
const emptyIcons = iconBlock ? [...iconBlock[1].matchAll(/^ {2}([a-z_][a-z0-9_]*)[ \t]*:[ \t]*''/gm)].map((m) => m[1]) : [];
if (emptyIcons.length) fail.push(`${TS_ICONS} 有以下键的 path 是空串（图标会渲成一个不可见轮廓）：${emptyIcons.join(', ')}`);
cmp('图标表键集 ↔ 派生全集 ∪ 客户端行种类', iconKeys && iconKeys.length ? iconKeys : null, CONSUME_SET);

/* ---- 齿 B：events.css 的 accent 规则 ---- */
const cssText = rdWeb(CSS_EVENTS);
const cssClassSet = [...new Set([...cssText.matchAll(/\.ev--([a-z_]+)/g)].map((m) => m[1]))].sort();
if (cssClassSet.length === 0) {
  fail.push(`${CSS_EVENTS} 里一条 .ev-- 都读不到（选择器形状变了，先核对再改门禁）`);
}
cmp('events.css 的 .ev-- 集 ↔ 派生全集 ∪ 客户端行种类', cssClassSet.length ? cssClassSet : null, CONSUME_SET);
/* 只校“名字存在”不够：`.ev--x { }` 也能匹上。每一类**派生事件**必须真拿到一条
 * `border-left-color`（accent 通道本体），否则那行只有图标有色、竖条回到默认 --border-decor。 */
if (EVENT_SET) {
  const noAccent = EVENT_SET.filter((n) => !new RegExp(`\\.ev--${n}\\b[^{}]*\\{[^}]*border-left-color`).test(cssText));
  if (noAccent.length) fail.push(`${CSS_EVENTS} 里以下事件没有 border-left-color 规则（class 名在但没上色）：${noAccent.join(', ')}`);
}
/* 消费侧得真的在用：`Timeline.vue` 不调 rowClassOf/iconPathOf，那上面两格守的是死代码。 */
for (const fn of ['rowClassOf', 'iconPathOf']) {
  if (!rdWeb(VUE_TIMELINE).includes(`${fn}(`)) {
    fail.push(`${VUE_TIMELINE} 没有调用 ${fn}( ⇒ 图标表/accent 两枚齿守的是死代码，消费链断在渲染层`);
  }
}

/* ---- 齿 C：凭据存储面（工单件 §2.3）----
 * 白名单**双向**：列了却不用也算漂移（与公开镜像 lint 的登记制同一条纪律：台账不能只进不出）。
 * 写这一格的时机是 PR-2：`session.ts`/`ApiKeyBox.vue` 开始真的往界面上接密钥，
 * 「只存内存」自此才有可违反面 —— 在那之前它只是一句注释。
 * ⚠ 判的是**调用形状**而不是词形：`localStorage\.(getItem|setItem|removeItem|clear)`。
 *   只匹字面词会把“不落 localStorage”这句屏上承诺也算成越界（那句是纪律的一部分，
 *   不是违反）——而把误报当代价接受就会有人开始写 `local` + `Storage` 拼串来绕过门禁。 */
const STORAGE_WL = ['theme.ts'];
const srcFiles = [];
(() => {
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.(ts|vue)$/.test(name)) srcFiles.push(p);
    }
  };
  walk(join(WEB, 'src'));
})();
const storageUsers = srcFiles
  .filter((p) => /\b(?:localStorage|sessionStorage)\s*\.\s*(?:getItem|setItem|removeItem|clear)\b/.test(readText(p))
    || /\bindexedDB\s*\.\s*open\b/.test(readText(p))
    || /\bdocument\s*\.\s*cookie\s*=/.test(readText(p)))
  .map((p) => p.split(/[\\/]/).pop())
  .sort();
const storageUnexpected = storageUsers.filter((f) => !STORAGE_WL.includes(f));
const wlStale = STORAGE_WL.filter((f) => !storageUsers.includes(f));
if (storageUnexpected.length) {
  fail.push(`凭据纪律越界（工单件 §2.3）：以下文件写了浏览器存储 API：${storageUnexpected.join(', ')}（白名单只允许主题偏好，见 ${STORAGE_WL.join(', ')}）`);
}
if (wlStale.length) {
  fail.push(`存储白名单陈旧：${wlStale.join(', ')} 已在名单里却不再写存储 API（台账只进不出 ⇒ 把它从白名单删掉）`);
}
note.push(`凭据面：写存储的文件 ${storageUsers.length ? storageUsers.join(', ') : '（无）'} / 白名单 ${STORAGE_WL.join(', ')} ${storageUnexpected.length + wlStale.length === 0 ? '✅' : '❌'}`);

/* ---- 接线断言：本件的调用链在不在 ---- */
/* 诚实边界（必须带着读）：这一格能抓的是「链上某被拆了一环」（Makefile 行被删、scripts 键被改名），
 * **抓不到「整条链被拆」**——本件自己不住在链上时它根本不会执行。整条链的静态对拍属
 * `e19-wiring-check` 那类取证件的射程（本地件，不入库），且 §12 反证表第 5 行要求的是
 * "只改 web/ 的提交必须让 CI 跑"，那是 workflow `paths:` 的事，不属本件。 */
const makeTxt = readText(join(ROOT, 'Makefile'));
const ciWebBody = (() => {
  const lines = makeTxt.split('\n');
  const start = lines.findIndex((l) => /^ci-web:/.test(l));
  if (start < 0) {
    fail.push('读不到 Makefile 的 ci-web: 目标（前端面门禁的落点坐标变了，先核对再改门禁）');
    return null;
  }
  const body = [];
  for (let i = start + 1; i < lines.length; i++) {
    if (!/^\t/.test(lines[i])) break;                     //  recipe 行以制表符开头，断了就是目标结束
    body.push(lines[i]);
  }
  return body.join('\n');
})();
if (ciWebBody !== null) {
  for (const [key, probe] of [['check:events', 'pnpm run check:events'], ['verify:sse', 'pnpm run verify:sse']]) {
    if (!ciWebBody.includes(probe)) fail.push(`Makefile 的 ci-web 目标里没有「${probe}」（本门禁被拆链，${key} 不会随 make ci-web 执行）`);
  }
}
const pkgJson = JSON.parse(rd('web/package.json'));
for (const key of ['check:events', 'verify:sse']) {
  const v = pkgJson?.scripts?.[key];
  if (typeof v !== 'string' || !v.includes('scripts/')) {
    fail.push(`web/package.json 的 scripts.${key} 缺失或不指向 scripts/（${key} 是本件与行为件的唯一入口）`);
  }
}

/* ---- 输出 ---- */
console.log(`派生集（不写死条数）：Literal ${LITERAL ? LITERAL.length : '不可读'} + 实现下发 ${emitted.size} ⇒ 全集 ${EVENT_SET ? EVENT_SET.length : '不可读'} 类`);
console.log(`  全集成员：${EVENT_SET ? EVENT_SET.join(', ') : '（读不到）'}`);
for (const n of note) console.log('  ' + n);
if (fail.length) {
  console.log(`\n❌ 事件契约门禁失败（${fail.length} 条）：`);
  for (const f of fail) console.log('  · ' + f);
  process.exit(1);
}
console.log('\n✅ 事件契约门禁通过');
