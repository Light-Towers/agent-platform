#!/usr/bin/env node
/* ============================================================================
 * verify-kb-render.mjs — 知识库切片正文的**真组件渲染**验证（本地，无需部署/浏览器）
 *
 * 用 Vite SSR 把 KbContentText.vue 真渲染成 HTML 字符串，喂生产真实切片语料，
 * 断言浏览器将看到的结果：'##' 不出现、<h2>/<table> 出现、图片在正确位置。
 * 这补上 verify-markdown.mjs（只测解析器）与"目视复核"（需部署）之间的缺口：
 * 本地即可证明渲染层把标记处理成了人可读结构。
 *
 * 边界：SSR 不执行客户端 fetch，AuthImage 此时渲染的是 <span 加载中…> 占位
 * （真实 <img src=blob> 由浏览器端 fetchImageBlob 完成后才出现）⇒ 本脚本验证的是
 * "图片 token 在正文正确位置被渲染成 AuthImage 占位"，不声称验证了最终图片字节。
 *
 * 加载失败必须 rc=1（不把跑不动吞成跳过）。
 * ==========================================================================*/
import { createServer } from 'vite'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
// @vue/server-renderer 是 Vite SSR 的间接依赖（pnpm store 里有，但未 link 到顶层）。
// 走 store 相对路径 import，避免改 package.json / pnpm-lock（治本不改依赖树）。
const { renderToString } = await import(
  './../node_modules/.pnpm/@vue+server-renderer@3.5.44/node_modules/@vue/server-renderer/dist/server-renderer.esm-bundler.js'
)

let failures = 0
const ok = (cond, name, extra) => {
  if (cond) console.log('  ✓', name)
  else { console.log('  ✗', name, extra ?? ''); failures += 1 }
}

// 生产真实语料（取自 知识图谱 概念与技术3 首片，plan-kb-chunk-markdown-render 取证）
const REAL_CHUNK = `《知识图谱: 概念与技术》

# 第 3 讲关系抽取

肖仰华

复旦大学

## 本章大纲

• 1、关系抽取概述

• 2、基于Rule的关系抽取

命名实体标签帮助关系分类：

<table><tr><td>Pattern</td><td>Example occurrence</td></tr><tr><td>PERSON, POSITION of ORG</td><td>George Marshall was named US Secretary of State</td></tr></table>

特朗普<sup>“</sup>新政<sup>”</sup>确实有效提振了美国经济

![YAGO知识库标志，用于说明关系抽取在自动化知识库构建中的应用与意义。](http://minio:9000/kb-import-bucket/images/知识图谱概念与技术3/bfcfe9.jpg)`

let vite
try {
  vite = await createServer({
    configFile: 'vite.config.ts', // 复用项目配置里的 @vitejs/plugin-vue（.vue SSR transform）
    root: process.cwd(),
    server: { middlewareMode: true },
    appType: 'custom',
    logLevel: 'error',
  })
  const mod = await vite.ssrLoadModule('/src/components/KbContentText.vue')
  const Comp = mod.default
  // AuthImage 内部读 Pinia store（authToken），SSR 需显式装 Pinia，否则 setup 抛错。
  const renderComp = (content) => {
    const app = createSSRApp({ render: () => h(Comp, { content }) })
    app.use(createPinia())
    return renderToString(app)
  }
  const html = await renderComp(REAL_CHUNK)

  console.log('§A 真组件渲染结果（KbContentText.vue ← 生产切片语料）')
  ok(!html.includes('##'), 'A1 渲染结果不含字面 ## 标记')
  ok(html.includes('<h1') && html.includes('第 3 讲关系抽取'), 'A2 一级标题渲染成 <h1>')
  ok(html.includes('<h2') && html.includes('本章大纲'), 'A3 二级标题渲染成 <h2>')
  ok(html.includes('<table') && html.includes('</table>'), 'A4 HTML 表格渲染成真 <table>')
  ok(html.includes('George Marshall'), 'A5 表格单元格内容上屏')
  ok(html.includes('md-text__sup'), 'A6 <sup> 渲染成真上标（class=md-text__sup）')
  ok(!html.includes('<table><tr>'), 'A7 原始标签串没有原样漏到界面')
  ok(html.includes('rich-img-loading'), 'A8 图片 token 在正文渲染成 AuthImage（SSR 占位）')
  ok(html.indexOf('George Marshall') < html.indexOf('rich-img-loading'), 'A9 表格在图片之前（顺序保持）')

  console.log('§B 边界：关系元组不被误剥')
  const tupleHtml = await renderComp('ORGANIZATION {<headquarters 0.7> <in 0.7>}')
  ok(tupleHtml.includes('&lt;headquarters 0.7&gt;') || tupleHtml.includes('<headquarters 0.7>'),
     'B1 关系元组作为文本保留（HTML 转义后仍是字面元组）')
} catch (err) {
  console.error('渲染加载失败：', err?.message ?? err)
  failures += 1
} finally {
  await vite?.close()
}

console.log(`\n合计：${failures === 0 ? '全部通过' : failures + ' 条失败'}`)
process.exit(failures === 0 ? 0 : 1)
