#!/usr/bin/env node
/* ============================================================================
 * check-tokens.mjs — 视觉门禁六条断言（视觉件 §6）
 * 零依赖：只用 Node 内置 fs/path。挂 `make ci-web`，**不进 `make ci`**。
 *
 * 定性（必须带着读这份脚本）：本文件全部断言都是 `readFileSync` 文本/正则形状断言，
 * 属工单件 §10.5 已定性的**脆断言** —— 只用来锁**结构不变量**（令牌登记、双向覆盖、
 * 双写同值、字典 key 集 == 派生集），**没有一条锁行为**（不断言「route 事件渲染出来是蓝色」，
 * 那属 V2/V3 的截图判据）。
 *
 * 断言 6 的派生口径 = 取证件 §1 那一份的 Node 同形移植：
 *   事件集 = `StreamEventType` Literal ∪ 实现里以 `"type": "x"` / `type="x"` 形态下发的字面量
 *   字段集 = 两层 `HealthResponse` 的带注解赋值目标名并集（子类同名字段不重复计）
 * 期望集**只从源读**，本文件不出现 12 或 30 这两个数。
 *
 * 断言 1 的已知误报面（有意的 fail-closed，不改断言）：它扫**全文，含注释与文案**，
 * 所以上一条线提到的“注释里举反例”会被自己判红。POC 实踩两例：① 注释里写 `rgb(` 作解释；
 * ② 对话页会话列表里的工单编号（带 `#` 前缀）被当成色值字面量。两条都按“改文字形状、
 * 不收窄正则”处置 —— 把它收窄到“仅 CSS 声明上下文”会连带放过内联 style 里的硬编色，
 * 代价大于收益。本件不在扫描面内，所以下面举的色值形状只当说明、不会被判红。
 * ==========================================================================*/
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

/* 行尾归一：**所有**文本读取走这里。POC 首跑实踩：Windows checkout 是 CRLF，
 * 而断言 5 的锚点写了字面 `\n  }\n}` ⇒ 同一份门禁在 LF 环境绿、在 CRLF 环境红。
 * 判据随检出平台漂移 = 门禁不可复现。归一化只消除行尾差异，不动任何声明内容。 */
const readText = (p) => readFileSync(p, 'utf8').replace(/\r\n/g, '\n');

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const ROOT = join(WEB, '..');
const STYLE_DIR = join(WEB, 'src/styles');
const fail = [];
const note = [];

/* ---- 扫描面：样式三件 + 两个 POC 宿主页（PR-0 交付后此处换成 src 下 .vue 文件递归）。
 * 两页都在扫描面内：断言 1/2/4 是全文扫的，灯阵页新加的一条色值字面量不能逸出门禁。---- */
const targets = ['tokens.css', 'base.css', 'events.css']
  .map((f) => join(STYLE_DIR, f))
  .concat([join(WEB, 'poc.html'), join(WEB, 'poc-health.html')]);
const src = Object.fromEntries(targets.map((p) => [p, readText(p)]));
const tokensPath = join(STYLE_DIR, 'tokens.css');
const tokens = src[tokensPath];

/* 定义集：tokens.css 里的 `--x:` */
const defined = new Set(
  [...tokens.matchAll(/(--[A-Za-z0-9-]+)\s*:/g)].map((m) => m[1])
);
/* 引用集：全部目标文件里的 `var(--x)` */
const referenced = new Set();
for (const [p, text] of Object.entries(src)) {
  for (const m of text.matchAll(/var\((--[A-Za-z0-9-]+)\)/g)) referenced.add(m[1]);
}

/* 断言 1：tokens.css 之外不得出现 hex / rgb() / rgba() */
for (const [p, text] of Object.entries(src)) {
  if (p === tokensPath) continue;
  const hits = [...text.matchAll(/#[0-9a-fA-F]{3,8}\b|\brgba?\(/g)].map((m) => m[0]);
  if (hits.length) fail.push(`断言1 ${p.replace(ROOT, '')} 出现色值字面量：${[...new Set(hits)].join(', ')}`);
}

/* 断言 2：引用的令牌必须已登记 */
for (const v of referenced) {
  if (!defined.has(v)) fail.push(`断言2 引用了未登记令牌 ${v}`);
}

/* 断言 3：登记但无人引用 = 孤儿令牌，fail 而非 warn */
for (const d of defined) {
  if (!referenced.has(d)) fail.push(`断言3 孤儿令牌 ${d}（登记了无人引用；漂着的令牌下一批会被当成可调用的值）`);
}

/* 断言 4：字面量禁令（font-weight 三档 / 裸间距 / 裸行高 / 裸字距） */
for (const [p, text] of Object.entries(src)) {
  if (p === tokensPath) continue;
  for (const m of text.matchAll(/font-weight:\s*(\d+)\s*;/g)) {
    if (!['400', '500', '600'].includes(m[1])) {
      fail.push(`断言4 ${p.replace(ROOT, '')} font-weight:${m[1]} 只允许 400/500/600（未打包的字重会静默回落）`);
    }
  }
  for (const m of text.matchAll(/(?:^|[;{\s])(margin|padding|gap)(-block|-inline|-top|-bottom|-left|-right)?\s*:\s*([^;}]+)/g)) {
    const val = m[3];
    if (/\b\d+(\.\d+)?(px|rem|em)\b/.test(val)) {
      fail.push(`断言4 ${p.replace(ROOT, '')} ${m[1]}${m[2] || ''}:${val.trim()} 用了裸尺寸，只允许 var(--sp-*)`);
    }
  }
  for (const m of text.matchAll(/(?:^|[;{\s])(line-height|letter-spacing)\s*:\s*([^;}]+)/g)) {
    const val = m[2].trim();
    if (!val.startsWith('var(--lh-') && !val.startsWith('var(--ls-') && val !== 'normal') {
      fail.push(`断言4 ${p.replace(ROOT, '')} ${m[1]}:${val} 只允许 var(--lh-*) / var(--ls-*)（第四批新立令牌族的子句）`);
    }
  }
}

/* 断言 5：dark 两副本逐条同值（比较时忽略缩进与注释 —— 见下面 F2 说明） */
const normDecls = (body) =>
  body
    .split('\n')
    .map((l) => l.replace(/\/\*[\s\S]*?\*\//g, '').trim())
    .filter((l) => l && l.includes(':'));
const copyA = tokens.match(/@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme\]\) \{([\s\S]*?)\n  \}\n\}/);
const copyB = tokens.match(/:root\[data-theme="dark"\] \{([\s\S]*?)\n\}/);
if (!copyA || !copyB) {
  fail.push('断言5 找不到 dark 副本 A 或 B（主题机制双写缺失）');
} else {
  const a = normDecls(copyA[1]);
  const b = normDecls(copyB[1]);
  if (a.length !== b.length || a.some((l, i) => l !== b[i])) {
    const d = [];
    for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) d.push(`  A[${i}] ${a[i] || '(无)'}\n  B[${i}] ${b[i] || '(无)'}`);
    fail.push(`断言5 dark 双写漂移（${d.length} 条）：\n${d.slice(0, 8).join('\n')}`);
  }
}

/* ---- 断言 6：字典 key 集 == 从源派生的全集 ---- */
/* 源读失败的出口口径（第八批 ①，改这里前先读完这段）：
 * 过去 EVENTS / LAMP_WHY / 两层 HealthResponse class 头这三处读不到源走 `throw`，
 * 其余失败口（Literal、LAMP_GROUPS、断言 1~5）走 `fail.push` —— 同一个「读不到源」有两套
 * 出口。四口 rc 都是 1 分不出来，唯一可分的读数是 stdout 里有没有失败清单，而它只在
 * fail.push 那条成立 ⇒ 探针无法从屏上确认「这一口真的被走过」。
 * 现统一走 fail.push，并**读不到源就跳过该项双向比较**：只把 throw 换成 fail.push +
 * `return []` 是不够的 —— 空数组进 `cmp` 会被逐项报成「缺项 / 多项」，一条源坐标问题
 * 炸成整屏误报，反而把人往「字典写错了」的方向引。跳过只发生在该项的两侧之一不可信时，
 * 失败本身已计入 fail ⇒ rc 仍为 1，门禁不空转、也没有为了凑绿放宽断言。
 * 边界（有意不收）：`rd`/`readText` 的文件级 ENOENT 仍是未捕获 throw。文件在不在与
 * 文件里形状变没变是两类失败 —— 后者需要「报哪一条 + 跳过比较」，前者没有可跳过的对象，
 * 吞成 fail.push 只会丢掉 Node 自带的堆栈定位。要收得连扫描面一起收，属另一批。*/
const rd = (rel) => readText(join(ROOT, rel));
const PROTO = 'packages/agent-runtime/agent_runtime/planner/protocol.py';
const ROUTER = 'applications/agent_server/api/query_router.py';
const BASE_H = 'packages/shared-schemas/shared_schemas/health.py';
const APP_H = 'applications/agent_server/schemas.py';

const proto = rd(PROTO);
const literalBlock = proto.match(/StreamEventType\s*=\s*Literal\[(.*?)\]/s);
if (!literalBlock) fail.push('断言6 读不到 StreamEventType Literal（派生源坐标变了，须先核对再改门禁；事件项双向比较已跳过）');
const literal = literalBlock ? [...literalBlock[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]) : null;
const emitted = new Set();
for (const text of [proto, rd(ROUTER)]) {
  for (const re of [/"type":\s*"([a-z_]+)"/g, /type="([a-z_]+)"/g]) {
    for (const m of text.matchAll(re)) emitted.add(m[1]);
  }
}
const EVENT_SET = literal ? [...new Set([...literal, ...emitted])].sort() : null;

/* 类体里的带注解赋值目标名（跳过 docstring，docstring 内的中文冒号不参与） */
function healthFields(rel, cls) {
  const lines = rd(rel).split('\n');
  const start = lines.findIndex((l) => new RegExp(`^class ${cls}\\b`).test(l));
  if (start < 0) {
    fail.push(`断言6 ${rel} 里找不到 class ${cls}（/health 字段派生源坐标变了，先核对再改门禁；字段侧的双向比较已跳过）`);
    return null;
  }
  const out = [];
  let inDoc = false;
  for (let i = start + 1; i < lines.length; i++) {
    const l = lines[i];
    if (/^\S/.test(l) && l.trim() !== '') break;           // 退回列 0 ⇒ 类体结束
    const docCount = (l.match(/"""/g) || []).length;
    if (docCount % 2 === 1) { inDoc = !inDoc; continue; }
    if (inDoc) continue;
    const m = l.match(/^ {4}([A-Za-z_][A-Za-z0-9_]*)\s*:/); // ASCII 冒号，避开中文散文
    if (m) out.push(m[1]);
  }
  return out;
}
const baseF = healthFields(BASE_H, 'HealthResponse');
const subF = healthFields(APP_H, 'HealthResponse');
/* 任一层读不到 ⇒ 整个派生字段集不可信（缺一层就是缺若干字段，逐项比较只会报成"字典多了"） */
const FIELD_SET = baseF && subF ? [...new Set([...baseF, ...subF])].sort() : null;

/* 屏上字典：`EVENTS` 住在对话页，`LAMP_GROUPS` / `LAMP_WHY` 住在健康灯页
 * （用户 2026-10-30 拍板：灯阵从对话页第三栏移出成独立视图）。
 * 口径：只取**行首缩进后的第一个标识符**当 key —— 嵌套对象里的 `fam` / `sw` 前面是
 * `{ `不是纯空白，所以不会被误收；代价是字典必须**一行一键**（多键共一行会漏）。
 * 这是一条写进代码的耦合，不是隐形假设：两页的字典都按此形状排。 */
const talk = src[join(WEB, 'poc.html')];
const lampPage = src[join(WEB, 'poc-health.html')];
const dictKeys = (text, name, where) => {
  const block = text.match(new RegExp(`const ${name} = \\{([\\s\\S]*?)\\n\\};`));
  if (!block) {
    fail.push(`断言6 ${where} 里找不到 const ${name}（屏上字典坐标变了，先核对再改门禁；该项双向比较已跳过）`);
    return null;
  }
  return [...block[1].matchAll(/^[ \t]+([a-z_][a-z0-9_]*)[ \t]*:/gm)].map((m) => m[1]).sort();
};
const groupsBlock = lampPage.match(/const LAMP_GROUPS = \{([\s\S]*?)\n\};/);
if (!groupsBlock) fail.push('断言6 poc-health.html 里读不到 const LAMP_GROUPS（灯阵字典坐标变了，先核对再改门禁；分组项双向比较已跳过）');
const lampKeys = groupsBlock
  ? [...groupsBlock[1].matchAll(/\[([^\]]*)\]/g)].flatMap((m) => [...m[1].matchAll(/'([^']+)'/g)].map((x) => x[1]))
  : null;
/* 读不到就是 null，不在这里 .sort() / 展开 —— 坐标变了的情形必须能活着走到下面的跳过分支。 */
const EVENT_KEYS = dictKeys(talk, 'EVENTS', 'poc.html');
const LAMP_KEYS = lampKeys ? [...new Set(lampKeys)].sort() : null;
const WHY_KEYS = dictKeys(lampPage, 'LAMP_WHY', 'poc-health.html');

const diff = (a, b) => a.filter((x) => !b.includes(x));
const cmp = (label, dict, derived) => {
  if (!dict || !derived) {
    // 两侧之一读不到 ⇒ 不比。失败行已在上面 push 过，这里只补一条"确实跳过了"的可读数。
    note.push(`${label}：⚠ 跳过比较（${!derived ? '源侧' : '字典侧'}读不到，见上方失败行）`);
    return;
  }
  const miss = diff(derived, dict);   // 源里有、屏上没灯/没图例
  const extra = diff(dict, derived);  // 屏上有、源里没有
  if (miss.length) fail.push(`${label} 缺项（派生自源但字典没有）：${miss.join(', ')}`);
  if (extra.length) fail.push(`${label} 多项（字典有但源已不产出）：${extra.join(', ')}`);
  note.push(`${label}：字典 ${dict.length} / 派生 ${derived.length} ${miss.length + extra.length === 0 ? '✅' : '❌'}`);
};
cmp('断言6 事件图例字典', EVENT_KEYS, EVENT_SET);
cmp('断言6 /health 分组字典', LAMP_KEYS, FIELD_SET);
cmp('断言6 /health 说明字典', WHY_KEYS, FIELD_SET);

/* ---- 输出 ---- */
console.log(`派生集（不写死）：事件 ${EVENT_SET ? EVENT_SET.length : '不可读'} 类 / 字段 ${FIELD_SET ? FIELD_SET.length : '不可读'} 个`);
for (const n of note) console.log('  ' + n);
if (fail.length) {
  console.log(`\n❌ 视觉门禁失败（${fail.length} 条）：`);
  for (const f of fail) console.log('  · ' + f);
  process.exit(1);
}
console.log(`\n✅ 视觉门禁通过（定义 ${defined.size} / 引用 ${referenced.size}）`);
