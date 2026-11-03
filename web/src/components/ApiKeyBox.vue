<!-- ============================================================================
 * ApiKeyBox.vue — 密钥输入（工单件 §2.3 那条纪律的唯一屏上位）
 * 三条都在这个件里，各自可核：
 *   ① `type="password"`：屏上不回显明文（截图判据 V4 会拍到这一栏，明文上屏等于把
 *      凭据写进取证档）。
 *   ② **没有"应用"按钮**。参照物 `poc.html:68` 有那一枚，它在这里必须删：本件的模型值
 *      是 `session.ts` 里的 `apiKey`，`ask()` 发请求时直接读它 —— 加一个不改变任何状态
 *      的按钮就是假控件（与 PR-0 头注那句"不拿假数据顶位"同一条纪律，只是这次遮的是
 *      控件不是数据）。代价如实记：将来若密钥要"换了要重连"，那时它才有动作可做。
 *   ③ 那句"不落 localStorage"必须写在**屏上**而不只写在注释里：这条纪律给人的可核对
 *      方式就是"页面上明说"，读代码的人与用它的人都看到同一句承诺。
 * 值本身只活在 `session.ts` 的 ref 里，随页面卸载消失；本件不写任何存储 API
 * （全仓 `web/src/**` 唯一存储写者是 `theme.ts` 的 `ap.ui.theme`，那条由
 * `check-events.mjs` 的凭据断言机器校）。
 * ⚠ 本件没有 <style> 块，理由见 ThemeToggle.vue 头注；`.keybox` 住在 `base.css`，
 *   标题那一格复用 `base.css` 的 `.o-head-sm`（不为本件新立一枚类）。
 * ==========================================================================-->
<script setup lang="ts">
import { apiKey } from '../stores/session'
</script>

<template>
  <div class="keybox">
    <label
      class="o-head-sm"
      for="apiKeyInput"
    >API 密钥</label>
    <input
      id="apiKeyInput"
      v-model="apiKey"
      class="field"
      type="password"
      autocomplete="off"
      placeholder="粘贴密钥"
    >
    <p class="hint">
      密钥<strong>只存内存，不落 localStorage</strong>；留空则不带
      <code class="t-name">X-API-Key</code> 头。主题偏好键
      <code class="t-name">ap.ui.theme</code> 不属凭据，与这条纪律不冲突（视觉件 §1.6）。
    </p>
  </div>
</template>
