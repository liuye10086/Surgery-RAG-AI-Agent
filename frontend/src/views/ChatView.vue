<template>
  <div class="chat-view">
    <ChatSidebar
      :sessions="chatStore.sessions"
      :current-id="chatStore.currentSession?.id"
      :collapsed="sidebarCollapsed"
      @select="handleSelect"
      @new-session="handleNewSession"
      @toggle="toggleSidebar"
      @delete-session="handleDeleteSession"
    />

    <div class="chat-main">
      <div class="chat-header">
        <h2>{{ chatStore.currentSession?.title || '新会话' }}</h2>
        <div class="header-actions">
          <el-tooltip :content="panelVisible ? '隐藏信息来源 (Ctrl+B)' : '信息来源 (Ctrl+B)'" placement="bottom" :show-after="300">
            <el-button
              :class="['panel-toggle-btn', { active: panelVisible }]"
              :icon="Collection"
              size="small"
              text
              @click="togglePanel"
            />
          </el-tooltip>
          <el-button v-if="authStore.canAccessOperator" @click="$router.push('/operator')" size="small">AI 操作者</el-button>
          <el-button v-if="authStore.isAdmin" @click="$router.push('/admin')" size="small">管理后台</el-button>
        </div>
      </div>

      <div class="chat-body">
        <div class="chat-center">
          <div class="message-list" ref="messageListRef">
            <div class="message-list-inner">
            <template v-if="chatStore.currentSession">
              <div v-if="hasIncompleteGeneration" class="incomplete-tip">
                <el-icon><InfoFilled /></el-icon>
                上一条问题正在生成回答，请稍候刷新页面查看结果。
              </div>
              <ChatMessage
                v-for="msg in visibleMessages"
                :key="msg.id"
                :message="msg"
                :danger-warning="getDangerForMessage(msg)"
                @retry="handleRetry"
              />
              <div v-if="chatStore.loading" :class="['loading-row', { 'animations-paused': pageHidden }]">
                <div class="loading-avatar"></div>
                <div class="loading-content">
                  <div class="loading-indicator">
                    <div class="heartbeat-dots">
                      <span class="hb-dot" v-for="i in 3" :key="i" :style="{ animationDelay: `${(i - 1) * 0.18}s` }"></span>
                    </div>
                    <span class="loading-text">{{ chatStore.loading === 'retrieving' ? '正在检索知识库...' : '正在生成回答...' }}</span>
                  </div>
                </div>
              </div>
            </template>

            <!-- 空状态欢迎页 -->
            <div v-else class="welcome-page">
              <div class="welcome-icon">
                <el-icon :size="28"><ChatDotRound /></el-icon>
              </div>
              <h1 class="welcome-title">您好，有什么可以帮助您的？</h1>
              <p class="welcome-desc">
                您可以描述您的症状或健康疑问，我会参考医学知识库为您提供参考信息。
              </p>
              <div class="welcome-prompts">
                <span
                  v-for="prompt in suggestedPrompts"
                  :key="prompt"
                  class="prompt-tag"
                  @click="handlePromptClick(prompt)"
                >{{ prompt }}</span>
              </div>
            </div>
            </div>
          </div>

          <div class="chat-input-area">
            <div class="input-gradient"></div>
            <div class="input-wrapper">
              <el-input
                v-model="input"
                type="textarea"
                :rows="1"
                :autosize="{ minRows: 1, maxRows: 6 }"
                placeholder="请输入您想咨询的医学问题..."
                resize="none"
                @keydown.enter.prevent="handleSend"
                class="main-input"
              />
              <el-button
                :class="['send-btn', { 'has-text': input.trim() }]"
                :icon="Promotion"
                :disabled="!input.trim()"
                :loading="Boolean(chatStore.loading)"
                @click="handleSend"
                circle
              />
            </div>
            <!-- 科室筛选 -->
            <div class="dept-filter-row">
              <el-select
                :model-value="chatStore.selectedDepartmentId"
                @update:model-value="chatStore.setSelectedDepartmentId"
                placeholder="全部科室"
                clearable
                size="small"
                class="dept-select"
              >
                <el-option
                  v-for="d in departments"
                  :key="d.id"
                  :label="d.name"
                  :value="d.id"
                />
              </el-select>
              <span v-if="chatStore.selectedDepartmentId" class="dept-filter-tag">
                当前检索范围：{{ departments.find(d => d.id === chatStore.selectedDepartmentId)?.name }}
              </span>
            </div>
          </div>
        </div>

        <!-- 右侧信息来源面板（归入聊天区内部，header 不受影响） -->
        <InfoPanel
          :visible="panelVisible"
          :groups="sourceGroups"
          @close="panelVisible = false"
          @source-click="handlePanelSourceClick"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Promotion, InfoFilled, Collection } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import ChatSidebar from '@/components/ChatSidebar.vue'
import ChatMessage from '@/components/ChatMessage.vue'
import InfoPanel from '@/components/InfoPanel.vue'
import { listPublicDepartments, type DepartmentOut } from '@/api/admin'
import type { Message } from '@/api/chat'

const authStore = useAuthStore()
const chatStore = useChatStore()

const input = ref('')
const messageListRef = ref<HTMLDivElement | null>(null)
const pageHidden = ref(false)
const departments = ref<DepartmentOut[]>([])
const shouldFollowMessages = ref(true)
const scrollBottomThreshold = 72

// 侧边栏折叠状态（持久化到 localStorage）
const sidebarCollapsed = ref(localStorage.getItem('sidebar_collapsed') === 'true')

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('sidebar_collapsed', String(sidebarCollapsed.value))
  // 展开侧边栏时关闭信息来源面板（互斥）
  if (!sidebarCollapsed.value) {
    panelVisible.value = false
  }
}

// 信息来源面板状态（默认关闭，不持久化）
const panelVisible = ref(false)

function togglePanel() {
  panelVisible.value = !panelVisible.value
  // 展开信息来源面板时折叠侧边栏（互斥）
  if (panelVisible.value) {
    sidebarCollapsed.value = true
    localStorage.setItem('sidebar_collapsed', 'true')
  }
}

// 按问答对分组的来源
interface CollectedSource {
  chunk_id: number
  title?: string
  page_number?: number | null
  content?: string
  citation_index?: number
  document_id?: number
  images?: { url: string; page?: number }[]
  messageId: number
}

interface SourceGroup {
  question: string
  messageId: number
  sources: CollectedSource[]
}

const sourceGroups = computed<SourceGroup[]>(() => {
  const messages = chatStore.currentSession?.messages
  if (!messages) return []

  const groups: SourceGroup[] = []
  // 单次前向遍历，缓存最近一条用户问题，避免 O(n²) 反向扫描
  let lastUserQuestion = ''

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i]
    if (msg.role === 'user') {
      lastUserQuestion = msg.content
      continue
    }
    if (msg.role !== 'assistant' || !msg.sources?.length) continue

    groups.push({
      question: lastUserQuestion,
      messageId: msg.id,
      sources: msg.sources
        .map((s: any) => ({
          chunk_id: s.chunk_id,
          document_id: s.document_id,
          title: s.title || s.document_title,
          page_number: s.page_number,
          content: s.content || s.page_content,
          citation_index: s.citation_index,
          images: s.images || [],
          messageId: msg.id,
        }))
        .sort((a, b) => (a.citation_index ?? 0) - (b.citation_index ?? 0)),
    })
  }

  return groups
})

// 面板来源点击 → 滚动到对应来源
function handlePanelSourceClick(source: any) {
  // 先加载对应消息所在的会话（如果是当前会话则直接操作）
  const messages = chatStore.currentSession?.messages
  if (!messages) return

  // 找到包含该 chunk_id 的消息
  for (const msg of messages) {
    if (msg.role !== 'assistant' || !msg.sources?.length) continue
    const found = msg.sources.findIndex((s: any) => s.chunk_id === source.chunk_id)
    if (found !== -1) {
      const sourceEl = document.getElementById(`source-${msg.id}-${found}`)
      if (sourceEl) {
        sourceEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
        // 临时高亮
        sourceEl.classList.add('highlight')
        setTimeout(() => sourceEl.classList.remove('highlight'), 2000)
      }
      return
    }
  }
}

// 推荐问法
const suggestedPrompts = [
  '手术前需要注意什么？',
  '术后恢复期饮食建议',
  '这个检查结果怎么看？',
  '常见术后并发症有哪些？',
]

// 过滤掉空占位消息：流式内容到达前不渲染空白气泡，涵盖初发和重试
const visibleMessages = computed(() => {
  const msgs = chatStore.currentSession?.messages
  if (!msgs) return []
  return msgs.filter(m => {
    if (m.role === 'assistant' && !m.content && !m.sources?.length && !m.is_error && chatStore.loading) {
      return false
    }
    return true
  })
})

const hasIncompleteGeneration = computed(() => {
  const messages = chatStore.currentSession?.messages
  if (!messages || messages.length === 0) return false
  const last = messages[messages.length - 1]
  return last.role === 'user' && !chatStore.loading
})

const userMessageWithDanger = computed(() => {
  const msgs = chatStore.currentSession?.messages
  if (!msgs || !chatStore.dangerState) return null
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'user') return msgs[i].id
  }
  return null
})

function getDangerForMessage(msg: Message): { level: string; advice: string } | null {
  if (msg.role !== 'user') return null
  // 1) 优先从持久化映射查找（会话历史回访时 dangerState 已清空但仍可恢复）
  const persisted = chatStore.dangerByMessageId[msg.id]
  if (persisted) return persisted
  // 2) 实时流式期间：当前会话最新用户消息且 dangerState 已设置
  if (chatStore.dangerState && msg.id === userMessageWithDanger.value) {
    return chatStore.dangerState
  }
  return null
}

function beforeUnloadHandler(e: BeforeUnloadEvent) {
  if (chatStore.loading) {
    e.preventDefault()
    e.returnValue = ''
  }
}

watch(
  () => chatStore.loading,
  (loading) => {
    if (loading) {
      window.addEventListener('beforeunload', beforeUnloadHandler)
    } else {
      window.removeEventListener('beforeunload', beforeUnloadHandler)
    }
  }
)

onUnmounted(() => {
  window.removeEventListener('beforeunload', beforeUnloadHandler)
  chatStore.abort()
})

// ===== 键盘快捷键 =====
function handleKeydown(e: KeyboardEvent) {
  // Ctrl+B: 切换信息来源面板
  if (e.ctrlKey && e.key === 'b') {
    e.preventDefault()
    togglePanel()
  }
}

function handleVisibilityChange() {
  pageHidden.value = document.hidden
}

function isNearMessageBottom() {
  const el = messageListRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight <= scrollBottomThreshold
}

function handleMessageScroll() {
  shouldFollowMessages.value = isNearMessageBottom()
}

function scrollMessagesToBottom(behavior: ScrollBehavior = 'smooth') {
  const el = messageListRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior })
}

async function loadDepartments() {
  try {
    departments.value = await listPublicDepartments()
  } catch {
    // 科室加载失败不影响主流程
  }
}

onMounted(async () => {
  await chatStore.loadSessions()
  loadDepartments()
  window.addEventListener('keydown', handleKeydown)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  messageListRef.value?.addEventListener('scroll', handleMessageScroll, { passive: true })
  pageHidden.value = document.hidden
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  messageListRef.value?.removeEventListener('scroll', handleMessageScroll)
})

// ===== 消息操作 =====
// 监听消息数量变化 和 最后一条消息内容变化（流式输出时跟随滚动）
watch(
  () => {
    const msgs = chatStore.currentSession?.messages
    if (!msgs || msgs.length === 0) return ''
    const last = msgs[msgs.length - 1]
    return `${msgs.length}-${last.content?.length ?? 0}`
  },
  () => {
    // 页面隐藏时跳过自动滚动，减少后台渲染压力，避免窗口闪烁
    if (pageHidden.value || !shouldFollowMessages.value) return
    nextTick(() => {
      scrollMessagesToBottom('auto')
    })
  }
)

async function handleSelect(sessionId: number) {
  await chatStore.loadSession(sessionId)
  // 加载历史会话后瞬间滚到底部，等待 DOM 渲染完成
  await nextTick()
  shouldFollowMessages.value = true
  scrollMessagesToBottom('auto')
}

async function handleNewSession() {
  await chatStore.newSession('新会话')
}

async function handleSend() {
  const content = input.value.trim()
  if (!content || chatStore.loading) return
  if (!chatStore.currentSession) {
    await chatStore.newSession()
  }
  input.value = ''
  shouldFollowMessages.value = true
  await nextTick()
  scrollMessagesToBottom('auto')
  await chatStore.sendMessage(content)
}

async function handlePromptClick(prompt: string) {
  if (chatStore.loading) return
  if (!chatStore.currentSession) {
    await chatStore.newSession()
  }
  input.value = ''
  shouldFollowMessages.value = true
  await nextTick()
  scrollMessagesToBottom('auto')
  await chatStore.sendMessage(prompt)
}

function handleRetry(message: Message) {
  if (chatStore.loading) {
    ElMessage.warning('正在生成回答，请稍后再试')
    return
  }
  if (!chatStore.currentSession) return
  const messages = chatStore.currentSession.messages
  const index = messages.findIndex((m) => m.id === message.id)
  if (index <= 0) return

  for (let i = index - 1; i >= 0; i--) {
    if (messages[i].role === 'user') {
      chatStore.retryMessage(message, messages[i].content)
      return
    }
  }
}

async function handleDeleteSession(sessionId: number) {
  try {
    await ElMessageBox.confirm('确定删除该会话及其所有聊天记录吗？', '确认删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await chatStore.removeSession(sessionId)
    ElMessage.success('会话已删除')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.detail || '删除失败')
    }
  }
}
</script>

<style scoped>
.chat-view {
  display: flex;
  height: 100vh;
  background: var(--bg-surface);
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-canvas);
}

/* ===== 聊天主体（header 下方，消息区 + 面板） ===== */
.chat-body {
  flex: 1;
  display: flex;
  flex-direction: row;
  min-height: 0;
}

.chat-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* ===== 顶部 header ===== */
.chat-header {
  height: var(--topbar-height);
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.chat-header h2 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  margin-left: var(--space-4);
}

.panel-toggle-btn {
  color: var(--text-secondary);
  transition: color var(--duration-fast) ease-out;
}

.panel-toggle-btn.active {
  color: var(--color-primary);
}

/* ===== 消息列表 ===== */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6) var(--space-6);
}

.message-list-inner {
  max-width: 760px;
  margin: 0 auto;
}

/* ===== 欢迎页 ===== */
.welcome-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-10);
}

.welcome-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-light);
  border-radius: 50%;
  color: var(--color-primary);
  margin-bottom: var(--space-6);
}

.welcome-title {
  margin: 0 0 var(--space-3);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
}

.welcome-desc {
  margin: 0 0 var(--space-8);
  font-size: 15px;
  color: var(--text-secondary);
  text-align: center;
  max-width: 480px;
  line-height: 1.6;
}

.welcome-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  justify-content: center;
  max-width: 560px;
}

.prompt-tag {
  display: inline-block;
  padding: 8px 18px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition: border-color var(--duration-fast) ease-out,
              color var(--duration-fast) ease-out,
              background var(--duration-fast) ease-out;
  user-select: none;
}

.prompt-tag:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
}

/* ===== 加载指示器（心跳 + 跳动圆点） ===== */
/* 复用 ChatMessage 的消息行布局，头像占位自动对齐 */
.loading-row {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.loading-avatar {
  width: 28px;
  flex-shrink: 0;
}

.loading-content {
  max-width: 70%;
  min-width: 0;
}

.loading-indicator {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) 0;
  animation: heartbeat 1.2s ease-in-out infinite;
}

@keyframes heartbeat {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.03); }
}

.heartbeat-dots {
  display: flex;
  align-items: center;
  gap: 5px;
}

.hb-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-accent);
  animation: dot-bounce 1.2s ease-in-out infinite;
}

@keyframes dot-bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.3; }
  40% { transform: translateY(-7px); opacity: 1; }
}

.loading-text {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.incomplete-tip {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  padding: 10px 14px;
  background: var(--color-primary-light);
  border: 1px solid hsl(200, 65%, 80%);
  border-radius: var(--radius-item);
  color: var(--color-primary);
  font-size: var(--text-xs);
}

/* ===== 输入区域 ===== */
.chat-input-area {
  flex-shrink: 0;
  position: relative;
  padding: 0 var(--space-6) var(--space-6);
}

/* 科室筛选行 */
.dept-filter-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  max-width: 760px;
  margin: var(--space-2) auto 0;
  padding-left: var(--space-1);
}

.dept-select {
  width: 150px;
}

.dept-filter-tag {
  font-size: var(--text-xs);
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 1px 10px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.input-gradient {
  position: absolute;
  top: -40px;
  left: 0;
  right: 0;
  height: 40px;
  background: linear-gradient(transparent, var(--bg-canvas));
  pointer-events: none;
}

.input-wrapper {
  max-width: 760px;
  margin: 0 auto;
  position: relative;
}

.main-input {
  --input-radius: 12px;
}

.main-input :deep(.el-textarea__inner) {
  border-radius: 12px;
  border: 1px solid var(--border-default);
  background: var(--bg-surface);
  padding: 14px 52px 14px 16px;
  font-size: 15px;
  line-height: 1.5;
  min-height: 56px;
  max-height: 200px;
  resize: none;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--duration-fast) ease-out,
              box-shadow var(--duration-fast) ease-out;
}

.main-input :deep(.el-textarea__inner):hover {
  border-color: var(--text-disabled);
}

.main-input :deep(.el-textarea__inner):focus {
  border-color: var(--border-focus);
  box-shadow: var(--focus-ring);
}

.main-input :deep(.el-textarea__inner)::placeholder {
  color: var(--text-disabled);
}

/* 发送按钮（绝对定位于输入框内右侧） */
.send-btn {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 36px;
  height: 36px;
  min-height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color var(--duration-fast) ease-out,
              opacity var(--duration-fast) ease-out;
}

.send-btn:not(.has-text) {
  opacity: 0.35;
  pointer-events: none;
}

.send-btn.has-text {
  opacity: 1;
}

/* 页面隐藏时暂停无限动画，降低后台渲染压力，避免窗口闪烁 */
.animations-paused,
.animations-paused * {
  animation-play-state: paused !important;
}
</style>
