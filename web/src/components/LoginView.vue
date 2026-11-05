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
 * ⚠ 本件没有 <style> 块，理由见 ThemeToggle.vue 头注；用到的四个类
 *   （`.panel` `.field` `.btn` `.composer`）全住在 `base.css`，本件没为登录页新立一枚类。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  authMode,
  authNotice,
  authPending,
  enterWithApiKey,
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
  if (password.value === '') return '口令为空时不能提交'
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
  <main class="grid">
    <div class="col">
      <section
        class="panel"
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
            class="btn"
            :aria-pressed="isRegister"
            @click="pickMode('register')"
          >
            创建账号
          </button>
          <button
            type="button"
            class="btn"
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
            class="field"
            type="text"
            name="username"
            autocomplete="username"
            placeholder="例如 alice"
          >

          <label
            class="o-head-sm"
            :for="isRegister ? 'authNewPassword' : 'authPassword'"
          >口令</label>
          <!-- `type="password"`：屏上不回显明文（截图判据 V4 会拍到这一栏，与 ApiKeyBox 同一条纪律）。
               autocomplete 按两态分派：注册档要的是「新口令」（浏览器据此走生成器），
               登录档才是「当前口令」（据此填已存的）。写成常量会让密码管理器在注册时
               把旧口令填进来，那是当场能看见的错，不是假想。 -->
          <input
            :id="isRegister ? 'authNewPassword' : 'authPassword'"
            v-model="password"
            class="field"
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
              class="field"
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
              class="btn btn-primary"
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
            class="btn"
            @click="retryResume"
          >
            重试确认登录态
          </button>
        </p>
      </section>
    </div>

    <!-- 栏二：这一屏的承诺。写的全是**已成立**的事实，未来时的句子一句不要。 -->
    <div class="col">
      <section
        class="panel"
        aria-labelledby="hAuthNote"
      >
        <h2 id="hAuthNote">
          这一屏承诺什么
        </h2>
        <p class="hint">
          口令只在服务端做散列比对（argon2），<strong>不存明文、不进日志、不出本请求</strong>；
          登录那一路不区分「账号不存在」与「口令不对」，两者共用一句提示；但「创建账号」那一发
          撞出的 409 确实会告诉你某个名字已被占用 —— 那是开放自助注册的必然代价，不是漏。
        </p>
        <p class="hint">
          建号成功后即等于已登录（同一次往返拿到令牌）；名字已被占用时，同一次提交<strong>直接改用口令登录</strong>，
          不必再点一次 —— 只有口令也不对时才落回一句提示。表内零用户时，第一个建号的人就是管理员；
          之后建的都是普通账号。
        </p>
        <p class="hint">
          令牌存在本标签页的 <code class="t-name">sessionStorage</code>（键
          <code class="t-name">ap.auth.token</code>）：<strong>关掉标签即失效</strong>，刷新仍在。
          它不存 <code class="t-name">localStorage</code>，也不带口令。
        </p>
        <p class="hint">
          同企业的两个账号<strong>不共用一条会话线</strong>（会话主体按服务端断言的人分桶）。
          但「会话历史列表」这一格还没做：它要等 conversations 的写入点（PR-3），
          现在没有可追溯的来源，所以屏上不给它留位置。
        </p>
        <div class="keybox">
          <button
            type="button"
            class="btn"
            @click="enterWithApiKey"
          >
            不登录，用 API 密钥进入
          </button>
          <p class="hint">
            后端未启用登录面时（没配 <code class="t-name">DATABASE_URL</code> 或没挂签名密钥 ⇒
            登录接口回 503）这是唯一通路。密钥与令牌<strong>二选一</strong>：带令牌时不再发
            <code class="t-name">X-API-Key</code>，两条通道的装配规则住在
            <code class="t-name">src/api/auth.ts</code> 一处。
          </p>
        </div>
      </section>
    </div>
  </main>
</template>
