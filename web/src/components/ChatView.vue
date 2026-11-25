<!-- ============================================================================
 * ChatView.vue — 对话视图（R4 从 App.vue 拆出，路由 `/chat/:sessionId?`）
 * 三栏：左会话目录 / 中消息流+提交 / 右可核抽屉（仅 admin 点开）。
 * URL 的 :sessionId 与 store 的 activeSessionId 双向同步：深链刷新直达、侧栏切换改地址栏。
 * 本件无 <style> 块，形状类落 base.css（理由见 ThemeToggle.vue 头注）。
 * ==========================================================================-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import ChatStream from './ChatStream.vue'
import EvidenceList from './EvidenceList.vue'
import Legend from './Legend.vue'
import Timeline from './Timeline.vue'
import { useConversationsStore } from '../stores/conversations.ts'
import { useSessionStore } from '../stores/session.ts'
import { listKnowledgeBases, type KbKnowledgeBase } from '../api/kb.ts'
import { confirmDestructive } from '../utils/confirm.ts'

/** 会话删除二次确认（不可逆）：取消不删，确认才调 removeSession。 */
function onRemoveSession(id: string, title: string): void {
  if (!confirmDestructive({
    action: '删除会话',
    target: title,
    consequence: '该会话及全部对话历史将被永久移除。',
    reversible: false,
  })) return
  void removeSession(id)
}

const route = useRoute()
const router = useRouter()
const conversationsStore = useConversationsStore()
const sessionStore = useSessionStore()
const {
  activeSessionId, conversationsBusy, conversationsNotice, sessionList,
} = storeToRefs(conversationsStore)
const {
  loadHistory, loadSessions, newSession, removeSession, renameSession, selectSession, askCurrent,
} = conversationsStore
const {
  authRole, authToken, busy, canSubmit, evidence, eventCount, knowledgeScope, pendingImages, question, terminal, traceNote, waiting,
} = storeToRefs(sessionStore)
const { resetRound, abortCurrent } = sessionStore
import { applyCredentialHeaders } from '../api/auth.ts'
import { extractImageFiles } from '../utils/clipboard.ts'

/* 会话传图（plan-image-qa-fullstack）：本地预览 + 上传后的不透明 ref。
 * 图片先 POST /chat/upload-image 存 PG，返回 ref 进 pendingImages，随 /query 发送。 */
const imagePreview = ref<string[]>([])
const imageUploadError = ref('')
/** 单张图片上传（P3 单一实现）：选文件与粘贴两条入口共用同一套校验/上传/预览。 */
async function uploadImageFile(file: File): Promise<void> {
  if (!file.type.startsWith('image/')) {
    imageUploadError.value = '仅支持图片文件'
    return
  }
  if (pendingImages.value.length >= 4) {
    imageUploadError.value = '最多 4 张图片'
    return
  }
  const form = new FormData()
  form.append('file', file)
  form.append('session_id', activeSessionId.value || '')
  const headers = new Headers()
  applyCredentialHeaders(headers, { token: authToken.value })
  try {
    const resp = await fetch('/chat/upload-image', { method: 'POST', headers, body: form })
    if (!resp.ok) {
      imageUploadError.value = `上传失败（HTTP ${resp.status}）`
      return
    }
    const data = await resp.json() as { image_ref?: string }
    if (data.image_ref) {
      pendingImages.value = [...pendingImages.value, data.image_ref]
      imagePreview.value = [...imagePreview.value, URL.createObjectURL(file)]
    }
  } catch {
    imageUploadError.value = '图片上传失败（服务端不可达）'
  }
}

async function onPickImage(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''  // 允许重复选同一张
  imageUploadError.value = ''
  for (const file of files) await uploadImageFile(file)
}

/** 粘贴图片提问：剪贴板里的图片 File 直接走与选文件相同的上传链路。
 *  图片是"附带"不是文字，阻止默认行为避免被塞进 question 输入框。 */
async function onPasteImage(event: ClipboardEvent): Promise<void> {
  const files = extractImageFiles(event.clipboardData?.items)
  if (files.length === 0) return  // 纯文本粘贴照常，不干预
  event.preventDefault()
  imageUploadError.value = ''
  for (const file of files) await uploadImageFile(file)
}

/** 「查看过程」开关：仅 admin 可见，判据用服务端回读的角色码。 */
const canInspect = computed(() => authRole.value === 'admin')
const showInspector = ref(false)

/* 知识范围清单：本视图的局部 UI 态。拉取失败不拦提问，只退化成「全部知识库」一项。 */
const knowledgeBases = ref<readonly KbKnowledgeBase[]>([])
const knowledgeBasesNotice = ref('')
async function refreshKnowledgeBases(): Promise<void> {
  try {
    knowledgeBases.value = await listKnowledgeBases(authToken.value)
    knowledgeBasesNotice.value = ''
  } catch (err) {
    knowledgeBasesNotice.value = err instanceof Error ? err.message : String(err)
  }
}

/* 深链 → store：子组件的 mounted 先于父组件 App 的 mounted，故这里先落选中 id，
 * App 随后的 loadSessions 不会用「最近活跃」把深链覆盖掉。 */
watch(() => route.params.sessionId, async (sid) => {
  if (typeof sid === 'string' && sid !== '' && sid !== activeSessionId.value) {
    await selectSession(sid)
  }
}, { immediate: true })

/* store → 地址栏：侧栏切换与新建后把当前会话写进 URL，前进/后退因此可还原。 */
async function pickSession(id: string): Promise<void> {
  await selectSession(id)
  await router.push({ name: 'chat', params: { sessionId: id } })
}
async function createSession(): Promise<void> {
  await newSession()
  if (activeSessionId.value) await router.push({ name: 'chat', params: { sessionId: activeSessionId.value } })
}

onMounted(() => { void refreshKnowledgeBases() })

const submitHint = computed(() =>
  waiting.value
    ? '等待 done…（判定完成只看 done 帧，转圈不是完成信号）'
    : canSubmit.value ? '' : '输入为空时不能提交')

async function submit(): Promise<void> {
  await askCurrent()
  for (const url of imagePreview.value) URL.revokeObjectURL(url)
  imagePreview.value = []
  imageUploadError.value = ''
  await loadHistory()
  resetRound()
  await loadSessions()
  if (activeSessionId.value && route.params.sessionId !== activeSessionId.value) {
    await router.replace({ name: 'chat', params: { sessionId: activeSessionId.value } })
  }
}

const editingId = ref<string>('')
const draftTitle = ref('')
function startRename(s: { session_id: string; title: string }): void {
  editingId.value = s.session_id
  draftTitle.value = s.title
}
function cancelRename(): void {
  editingId.value = ''
  draftTitle.value = ''
}
async function commitRename(id: string): Promise<void> {
  const title = draftTitle.value.trim()
  if (!title) { cancelRename(); return }
  await renameSession(id, title)
  cancelRename()
}
</script>

<template>
  <div
    class="chat-shell"
    :class="{ 'chat-shell--no-inspector': !showInspector }"
  >
    <!-- 左：会话目录 -->
    <aside class="chat-shell__sidebar ry-card">
      <div class="chat-shell__side-head">
        <h2 id="hSessions">
          会话
          <span class="count-badge">{{ sessionList.length }}</span>
        </h2>
        <button
          type="button"
          class="ry-btn ry-btn--primary"
          :aria-disabled="conversationsBusy"
          @click="createSession"
        >
          {{ conversationsBusy ? '…' : '+ 新建' }}
        </button>
      </div>
      <p
        v-if="conversationsNotice"
        class="banner"
      >
        <strong>{{ conversationsNotice }}</strong>
      </p>
      <ul class="session-list">
        <li
          v-for="s in sessionList"
          :key="s.session_id"
          class="session-list__item"
          :class="{ 'is-active': s.session_id === activeSessionId }"
        >
          <template v-if="editingId === s.session_id">
            <input
              v-model="draftTitle"
              class="ry-input session-list__edit"
              type="text"
              maxlength="200"
              :aria-label="`修改会话标题 ${s.title}`"
              @keydown.enter="commitRename(s.session_id)"
              @keydown.esc="cancelRename"
            >
            <button
              type="button"
              class="ry-btn ry-btn--text session-list__edit-ok"
              :aria-label="`保存标题 ${s.title}`"
              @click="commitRename(s.session_id)"
            >
              ✓
            </button>
            <button
              type="button"
              class="ry-btn ry-btn--text session-list__edit-cancel"
              :aria-label="'取消修改标题'"
              @click="cancelRename"
            >
              ✕
            </button>
          </template>
          <template v-else>
            <button
              type="button"
              class="ry-btn ry-btn--text session-list__pick"
              :aria-current="s.session_id === activeSessionId ? 'true' : undefined"
              @click="pickSession(s.session_id)"
            >
              {{ s.title || s.session_id }}
            </button>
            <button
              type="button"
              class="ry-btn ry-btn--text session-list__rename"
              :aria-label="`修改标题 ${s.title}`"
              @click="startRename(s)"
            >
              ✎
            </button>
            <button
              type="button"
              class="ry-btn ry-btn--text session-list__del"
              :aria-label="`删除会话 ${s.title}`"
              @click="onRemoveSession(s.session_id, s.title)"
            >
              ×
            </button>
          </template>
        </li>
      </ul>
      <p
        v-if="!sessionList.length"
        class="hint"
      >
        还没有会话。直接提问会自动建一个。
      </p>
    </aside>

    <!-- 中：消息流 + 提交区 -->
    <section class="chat-shell__main ry-card">
      <ChatStream />
      <div
        v-if="canInspect"
        class="chat-shell__inspect-toggle"
      >
        <button
          type="button"
          class="ry-btn ry-btn--text"
          :aria-expanded="showInspector"
          @click="showInspector = !showInspector"
        >
          {{ showInspector ? '收起过程（依据/事件/图例）' : '查看过程（依据/事件/图例 · 仅管理员）' }}
        </button>
      </div>
      <p
        v-if="showInspector && (busy || eventCount > 0)"
        class="hint chat-shell__trace"
      >
        {{ traceNote }}
      </p>
      <form
        class="composer chat-shell__composer"
        @submit.prevent="submit"
      >
        <input
          v-model="question"
          class="ry-input"
          type="text"
          placeholder="输入问题，Enter 发送…（可直接粘贴图片）"
          autocomplete="off"
          aria-label="问题"
          @paste="onPasteImage"
        >
        <div
          v-if="imagePreview.length > 0"
          class="composer__images"
        >
          <img
            v-for="(src, i) in imagePreview"
            :key="src"
            :src="src"
            class="composer__thumb"
            :alt="`待发送图片 ${i + 1}`"
          >
          <span class="hint">本轮附带 {{ imagePreview.length }} 张图片</span>
        </div>
        <div class="composer__row">
          <label class="o-head-sm">
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              multiple
              class="composer__file"
              aria-label="上传图片提问"
              @change="onPickImage"
            >
            图片
          </label>
          <span
            v-if="imageUploadError !== ''"
            class="hint"
          >{{ imageUploadError }}</span>
          <label class="o-head-sm">
            知识范围
            <select
              v-model="knowledgeScope"
              class="ry-input"
              aria-label="知识范围（检索收窄到所选知识库）"
            >
              <option value="">
                全部知识库
              </option>
              <option
                v-for="kb in knowledgeBases"
                :key="kb.knowledge_id"
                :value="kb.knowledge_id"
              >
                {{ kb.name || kb.knowledge_id }}（{{ kb.doc_count }} 篇）
              </option>
            </select>
          </label>
          <button
            type="submit"
            class="ry-btn ry-btn--primary"
            :aria-disabled="!canSubmit"
          >
            {{ busy ? '等待 done…' : '发送' }}
          </button>
          <span
            v-if="submitHint !== ''"
            class="hint"
          >{{ submitHint }}</span>
          <button
            v-if="terminal === 'failed' && !busy"
            type="button"
            class="ry-btn ry-btn--text"
            @click="submit"
          >
            重试本轮
          </button>
        </div>
        <p
          v-if="knowledgeBasesNotice !== '' || knowledgeBases.length === 0"
          class="hint"
        >
          {{ knowledgeBasesNotice !== ''
            ? `知识库清单未取到：${knowledgeBasesNotice}（不影响提问，检索仍覆盖全部知识库）`
            : '服务端暂无已登记知识库；在知识库页上传并填写知识库 ID 后，这里会出现候选项。' }}
        </p>
      </form>
    </section>

    <!-- 右：可核对抽屉 -->
    <aside
      v-if="showInspector"
      class="chat-shell__inspector"
    >
      <details class="ry-card">
        <summary>
          <span class="o-head-sm">依据列表</span>
          <span class="count-badge">{{ evidence.length }}</span>
        </summary>
        <EvidenceList />
      </details>
      <details class="ry-card">
        <summary>
          <span class="o-head-sm">事件时间线</span>
          <span class="count-badge">{{ eventCount }}</span>
        </summary>
        <Timeline @stop="abortCurrent" />
      </details>
    </aside>
  </div>
  <Legend v-if="showInspector" />
</template>
