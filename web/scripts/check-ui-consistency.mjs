#!/usr/bin/env node
/* ============================================================================
 * check-ui-consistency.mjs — 结构复用门禁（plan-ui-consistency-2026-11-19）
 *
 * 锁一条结构不变量：列表行的「描边浮起选中态」(蓝边 + raised 底色) 全仓恰好一处实现，
 * 且选择器必须正好是 .is-active（无前缀）。三个页面（会话列表 / 知识库侧栏 / 文档列表）
 * 共用它，杜绝 2026-11-19 审计发现的「同一套声明逐字复制三份」漂移。
 *
 * 脆断言：只锁结构，不锁渲染（渲染属 CDP 截图判据）。遵循 AGENTS.md 观测面规矩第8条：
 *   ① 真面参与判决——扫真实 base.css，找不到/多于一处即红；
 *   ② 合成违规能咬——内置「多一份 .rogue.is-active 声明」喂同一判定，期望判红，
 *      否则门禁自身瞎（报 SELF_TEST_FAIL）。
 * ==========================================================================*/
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const basePath = join(WEB, 'src/styles/base.css');
const readText = (p) => readFileSync(p, 'utf8').replace(/\r\n/g, '\n');
const base = readText(basePath);

/** 判定函数：返回 selector 列表——声明体同时含蓝边 + raised 底色的规则块。 */
function findSelectStateBlocks(css) {
  const out = [];
  // 先剥 CSS 注释（/* ... */）：注释里提到 .is-active 不是选择器本身，
  // 同 check-tokens 断言1 的全文扫坑——不剥会把注释文本当选择器，误报前缀化。
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const re = /([^{}]+)\{([^{}]+)\}/g;
  for (const m of clean.matchAll(re)) {
    const selector = m[1].trim().replace(/\s+/g, ' ');
    const body = m[2];
    if (/border-color\s*:\s*var\(--ry-primary\)/.test(body)
      && /background\s*:\s*var\(--bg-raised\)/.test(body)) {
      out.push(selector);
    }
  }
  return out;
}

const fail = [];
const blocks = findSelectStateBlocks(base);

// ① 真面判决：恰好一处，且选择器正好是 .is-active
if (blocks.length !== 1) {
  fail.push(`描边浮起选中态声明块应恰好 1 处，实际 ${blocks.length} 处：${JSON.stringify(blocks)}`);
} else if (blocks[0] !== '.is-active') {
  fail.push(`唯一选中态选择器应是 '.is-active'，实际 '${blocks[0]}'（前缀化=又在复制一份）`);
}

// ② 合成反证：用**固定的最小样本**（不依赖当前 base，避免真面被污染时连带误判），
//    样本含一份合法 .is-active + 一份违规 .rogue.is-active，喂同一判定必须判出 2 处才算能咬。
const SYNTHETIC = [
  '.is-active { border-color: var(--ry-primary); background: var(--bg-raised); }',
  '.rogue.is-active { border-color: var(--ry-primary); background: var(--bg-raised); }',
].join('\n');
const syntheticBlocks = findSelectStateBlocks(SYNTHETIC);
if (syntheticBlocks.length !== 2) {
  fail.push(`SELF_TEST_FAIL: 合成违规应判出 2 处，实际 ${syntheticBlocks.length}——门禁瞎了`);
}

if (fail.length) {
  console.error('❌ UI 结构复用门禁失败：');
  for (const f of fail) console.error('  ' + f);
  process.exit(1);
}
console.log(`✅ UI 结构复用门禁通过（选中态单一实现：${blocks[0]}，合成反证已咬）`);
