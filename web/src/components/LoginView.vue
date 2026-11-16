<!-- ============================================================================
 * LoginView.vue — 登录 / 创建账号的**同一个屏**（工单件 §7 PR-2b · 方案 §2 目标那句）
 * 用户原话是「如果没有用户，那登录界面创建用户，如果有账号，直接登录就行」⇒ 形态必须是
 * 一屏两态，不是两个页面、也不是两个入口：
 *   · 两态由 `.seg` 控件切（`aria-pressed` 绑**布尔**，同 ThemeToggle 那条在册坑）；
 *   · 提交「创建账号」成功 = 已登录（后端 201 直接回令牌，**没有第二次点击**）；
 *   · 提交「创建账号」撞上已有账号（409）⇒ 会话层当场切回「登录」态，并**用同一份凭据补发一发
 *     登录**，人不必要再点一次（「如果有账号，直接登录就行」要的就是一次提交）。四条边界与
 *     为什么不反过来（401 不自建号）住在 stores/session.ts 的 `submitCredentials` 头注。
 *
 * 三条刻意没做，都要读成"没做"而不是"做完了"：
 *   ① 前端不预校验登录名形状。规则（小写字母/数字/._- 与 3–32 位）住在服务端目录里，
 *      抄一份到这边就是第二个事实源；违规时 400 + 服务端原句会直接上屏（`authNotice`）。
 *      **复审触发条件**：目录把那条例写进了 `/openapi.json` 的 schema，届时可改为读源。
 *   ② 没有「忘记密码」。方案 §2 非目标在册（口令重置需要一条能出域的通道，本轮没有）。
 *   ③ 没有确认口令二次输入。演示期一条要求：建号即管理员（D-g），错拼的后果是当场登不进
 *      去再建一个 —— 而注册成功即登录，屏上会立刻显示身份，拼错了第一秒就看得见。
 *
 * 口令的落点（纪律②在屏上的实物）：`password` 是本组件的局部 ref，只在提交那一刻进请求体，
 * 成功之后**立即清掉**（`onSubmit` 那两行）；它不进会话层、不进存储、不进任何文案。
 * 令牌则相反：它是服务端签发的、要活过一次刷新，所以落 sessionStorage（D-k，理由与残余风险
 * 都写在 `api/auth.ts` 文件头，本件不复述）。
 * ⚠ 本件没有 <style> 块，理由见 ThemeToggle.vue 头注；用到的类（`.ry-card` `.seg` `.ry-input`
 *   `.composer` `.hint` `.banner`）全住在 `base.css` / `tokens.css`。
 *
 * 三条 2026-11-16 的形态改动（用户在内网部署后的登录页上实测提出，不是设计偏好）：
 *   ① **登录面不复用对话页的 `.grid`**。那套 `minmax(0,1.1fr) minmax(0,1.4fr)` 是对话页的
 *      两栏比例（会话 : 时间线）；借用它会把登录卡挤进 1.1fr 窄栏（≈36%），而说明文字占
 *      1.4fr（≈64%）——**说明文字反过来决定了登录框的尺寸**；且未登录态不套 `.ry-layout`
 *      （那个才有 `height:100vh`），`.grid` 自己只有 `margin-top` + `align-items:start`
 *      ⇒ 整块贴视口顶边。两个方向都不居中，就是屏上看到的那个样子。
 *      ⇒ 改为 `.auth-page`（单栏 + 居中 + 限宽，形状在 `base.css`），登录卡 420px 居中。
 *   ② **说明段从「平铺一栏」改为「默认收起的 <details>」**。原先它常驻在屏上（占 64% 宽度），
 *      而登录的人真正会问的问题只有四类（口令怎么存、令牌在哪、什么时候要重登、409 是什么），
 *      其余内容不必占首屏。
 *   ③ **正文删掉两句**：其一「会话历史列表这一格还没做，它要等 conversations 的写入点（PR-3）」
 *      ——那是**工程待办账**，PR-3 至今未落地（conversations 表与写入函数都在，生产代码零调用点），
 *      但它对登录者是零价值，放登录屏上只会被读成「这系统还没做完」；其二「同企业的两个账号
 *      不共用一条会话线」——用户不会同时开两个账号，无从感知。
 *      留下的四段都是**用户会直接遇到的行为**，且**全部仍成立**（argon2 散列 / 登录失败统一
 *      提示 / 注册撞名 409 / 首号即管理员，逐条对过后端实现，不是照抄旧文案）。
 *   ⚠ 两处**不得删**：令牌存储档位（`sessionStorage`）与令牌键名（`ap.auth.token`）——
 *      门禁齿 C2/C4 拿它们做件间对拍（键名与 `api/auth.ts` 的 `TOKEN_KEY` 必须同源），
 *      人在屏上读到的键名是取证入口（照着它去 devtools 里找）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  authMode,
  authNotice,
  authPending,
  hasStoredToken,
  resumeSession,
  submitCredentials,
  type AuthMode,
} from '../stores/session'

const login = ref('')
const password = ref('')
const displayName = ref('')

const isRegister = computed(() => authMode.value === 'register')

/** 提交钮的可用性。`authPending` 含「正在向后端确认」那一档 —— 那时手里可能已有一个在途请求。 */
const canSend = computed(() =>
  !authPending.value && login.value.trim() !== '' && password.value !== '')

/** 不可用态要说清**为什么**不能按（A4 在控件上的同一条要求）；三句互斥，最多同时出现一句。 */
const sendHint = computed(() => {
  if (authPending.value) return '正在等待后端回话…'
  if (login.value.trim() === '') return '登录名为空时不能提交'
  if (password.value === '') return '密码为空时不能提交'
  return ''
})

function pickMode(mode: AuthMode): void {
  authMode.value = mode
}

async function send(): Promise<boolean> {
  if (!canSend.value) return false
  const ok = await submitCredentials({
    login: login.value.trim(),
    password: password.value,
    displayName: displayName.value.trim(),
  })
  // 口令一成功就抹掉：它已经在服务端变成了散列，屏上这一份没有下一次用处。
  // 不清 displayName/登录名 —— 那是给人核对「我刚才登的是谁」的，而且 409→登录态那条路要用它。
  if (ok) password.value = ''
  return ok
}

function onSubmit(): void {
  void send()
}

/** 令牌还在、只是后端那一跑没答上来时的那枚按钮。它不重新登录，只是再问一次 `/auth/me`。 */
function retryResume(): void {
  void resumeSession()
}
</script>

<template>
  <main class="auth-page">
    <div class="auth-page__inner">
      <section
        class="ry-card auth-page__card"
        aria-labelledby="hAuth"
      >
        <h2 id="hAuth">
          登录 / 创建账号
        </h2>

        <div
          class="seg"
          role="group"
          aria-label="入口动作"
        >
          <button
            type="button"
            class="ry-btn"
            :aria-pressed="isRegister"
            @click="pickMode('register')"
          >
            创建账号
          </button>
          <button
            type="button"
            class="ry-btn"
            :aria-pressed="!isRegister"
            @click="pickMode('login')"
          >
            登录
          </button>
        </div>

        <form
          class="composer"
          @submit.prevent="onSubmit"
        >
          <label
            class="o-head-sm"
            for="authLogin"
          >登录名</label>
          <input
            id="authLogin"
            v-model="login"
            class="ry-input"
            type="text"
            name="username"
            autocomplete="username"
            placeholder="例如 alice"
          >

          <label
            class="o-head-sm"
            :for="isRegister ? 'authNewPassword' : 'authPassword'"
          >密码</label>
          <!-- `type="password"`：屏上不回显明文（截图判据 V4 会拍到这一栏）。
               autocomplete 按两态分派：注册档要的是「新口令」（浏览器据此走生成器），
               登录档才是「当前口令」（据此填已存的）。写成常量会让密码管理器在注册时
               把旧口令填进来，那是当场能看见的错，不是假想。 -->
          <input
            :id="isRegister ? 'authNewPassword' : 'authPassword'"
            v-model="password"
            class="ry-input"
            type="password"
            name="password"
            :autocomplete="isRegister ? 'new-password' : 'current-password'"
          >

          <template v-if="isRegister">
            <label
              class="o-head-sm"
              for="authDisplayName"
            >显示名（可选）</label>
            <input
              id="authDisplayName"
              v-model="displayName"
              class="ry-input"
              type="text"
              autocomplete="nickname"
              placeholder="屏上给人看的那一个名字"
            >
          </template>

          <div class="composer__row">
            <!-- 同 App.vue 的提交钮：用 aria-disabled 而不是原生 disabled（原生属性把控件从 tab 序
                 里抽走，键盘用户会在按下的一瞬间丢焦点，V6 那一格实测过）。真正的早退在 `send()` 里。 -->
            <button
              type="submit"
              class="ry-btn ry-btn--primary"
              :aria-disabled="!canSend"
            >
              {{ authPending ? '提交中…' : isRegister ? '创建并进入' : '登录' }}
            </button>
            <span
              v-if="sendHint !== ''"
              class="hint"
            >{{ sendHint }}</span>
          </div>
        </form>

        <p
          v-if="authNotice !== ''"
          class="banner"
          role="status"
          aria-live="polite"
        >
          {{ authNotice }}
        </p>

        <p
          v-if="hasStoredToken && authNotice === ''"
          class="hint"
        >
          <button
            type="button"
            class="ry-btn"
            @click="retryResume"
          >
            重试确认登录态
          </button>
        </p>
      </section>

      <!-- 说明段：默认收起（<details> 原生折叠，形状沿用 App.vue 窄栏那份的同一惯例）。
           标题从「这一屏承诺什么」改成用户语言；正文只留**用户会直接遇到的行为**。
           ⚠ 两处不得删（门禁齿 C2/C4 的对拍目标）：令牌存储档位与令牌键名 ——
           人在屏上读到的键名是取证入口（照着它去 devtools 里找），删了门禁即红。
           ⚠ 删掉的那句「会话历史列表这一格还没做（PR-3）」是**工程待办账**：
           PR-3 至今未落地（conversations 表与写入函数都在，生产代码零调用点），
           但它对登录者是零价值，放登录屏上只会被读成「这系统还没做完」。 -->
      <details class="ry-card auth-page__note">
        <summary>
          <span class="o-head-sm">登录说明（口令怎么存 · 令牌在哪 · 什么情况下要重新登录）</span>
        </summary>
        <p class="hint">
          口令只在服务端做 argon2 散列比对，<strong>不存明文、不进日志</strong>。
          登录失败不区分「账号不存在」与「密码不对」——两种情况共用同一句提示。
        </p>
        <p class="hint">
          创建账号成功<strong>即等于已登录</strong>（同一次往返就拿到令牌）；
          若这个名字已被占用，同一次提交会<strong>直接改用密码登录</strong>，不必再点一次
          —— 只有密码也不对时才落回一句提示。
        </p>
        <p class="hint">
          令牌只存在本标签页的 <code class="t-name">sessionStorage</code>（键
          <code class="t-name">ap.auth.token</code>）：<strong>关掉标签即失效</strong>，刷新仍在。
          它不存 <code class="t-name">localStorage</code>，也不带密码。
        </p>
        <p class="hint">
          系统里的<strong>第一个账号自动是管理员</strong>，之后创建的账号都是普通用户。
        </p>
      </details>
    </div>
  </main>
</template>
