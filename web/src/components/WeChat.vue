<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { MatchChat, MatchMessage, MatchRole, MatchSeat, ModelChoice } from '../api'

const props = defineProps<{
  open: boolean
  page: 'list' | 'thread' | 'models'
  chatId: string
  chats: MatchChat[]
  models: ModelChoice[]
  roles: MatchRole[]
  seat: MatchSeat | null
  seating: boolean
  probing: string
  shuffling: boolean
  rejected: Record<string, string>
  peeked: string
}>()

const emit = defineEmits<{
  close: []
  'open-list': []
  'open-chat': [id: string]
  'open-models': []
  'pick-model': [id: string]
  'pick-role': [id: string]
  shuffle: []
  peek: []
}>()

const query = ref('')
const scroller = ref<HTMLElement | null>(null)
const searchBox = ref<HTMLInputElement | null>(null)
const anchor = ref<HTMLElement | null>(null)
const seen = ref<Record<string, number>>({})
const motion = ref<'push' | 'pop'>('push')
const offset = ref({ x: 0, y: 0 })
const dragging = ref(false)
const stickToBottom = ref(true)
let drag: { id: number; x: number; y: number; ox: number; oy: number } | null = null
let followedChat = ''
let scrolling = 0

const active = computed(() => props.chats.find((chat) => chat.id === props.chatId) ?? null)

const title = computed(() => {
  if (props.page === 'models') {
    return props.seat?.name || '选模型'
  }
  if (props.page === 'thread') {
    return active.value?.title || '聊天'
  }
  return '微信'
})

const filteredModels = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) {
    return props.models
  }
  return props.models.filter((model) => model.id.toLowerCase().includes(needle) || model.title.toLowerCase().includes(needle))
})

const unreadTotal = computed(() => props.chats.reduce((sum, chat) => sum + unread(chat), 0))

watch(
  () => [props.open, props.page, props.chatId, transcript(active.value)] as const,
  async () => {
    if (props.chatId !== followedChat) {
      followedChat = props.chatId
      stickToBottom.value = true
    }
    if (props.open && props.page === 'thread' && active.value) {
      seen.value = { ...seen.value, [active.value.id]: active.value.messages.length }
    }
    await nextTick()
    scrollThread()
  },
)

watch(
  () => props.page === 'models' && props.open,
  (focus) => {
    if (focus) {
      query.value = ''
      void nextTick(() => searchBox.value?.focus())
    }
  },
)

watch(
  () => props.page,
  (next, previous) => {
    if (!previous) {
      return
    }
    const depth = { list: 0, thread: 1, models: 1 }
    motion.value = depth[next] < depth[previous] ? 'pop' : 'push'
  },
)

function scrollThread(): void {
  const element = scroller.value
  if (!element || !stickToBottom.value) {
    return
  }
  scrolling += 1
  element.scrollTop = element.scrollHeight
  requestAnimationFrame(() => {
    scrolling = Math.max(0, scrolling - 1)
  })
}

function onThreadScroll(): void {
  if (scrolling > 0) {
    return
  }
  const element = scroller.value
  if (!element) {
    return
  }
  const gap = element.scrollHeight - element.scrollTop - element.clientHeight
  stickToBottom.value = gap <= 12
}

function transcript(chat: MatchChat | null): string {
  if (!chat) {
    return ''
  }
  return chat.messages.map((message) => `${message.id}:${message.text}:${message.streaming}`).join('\n')
}

function unread(chat: MatchChat): number {
  if (props.open && props.page === 'thread' && props.chatId === chat.id) {
    return 0
  }
  return Math.max(0, chat.messages.length - (seen.value[chat.id] ?? 0))
}

function preview(chat: MatchChat): string {
  const last = chat.messages[chat.messages.length - 1]
  if (!last) {
    return '暂无消息'
  }
  const text = last.kind === 'system' ? last.text : `${last.name}：${last.text}`
  return text.length > 18 ? `${text.slice(0, 18)}…` : text
}

function back(): void {
  emit('open-list')
}

function onPointerDown(event: PointerEvent): void {
  const target = event.target
  if (!(target instanceof Element)) {
    return
  }
  if (target.closest('button, input, textarea, a')) {
    return
  }
  const current = event.currentTarget
  if (!(current instanceof HTMLElement)) {
    return
  }
  if (!target.closest('.nav') && target !== current && !target.classList.contains('phone')) {
    return
  }
  drag = { id: event.pointerId, x: event.clientX, y: event.clientY, ox: offset.value.x, oy: offset.value.y }
  dragging.value = true
  current.setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent): void {
  if (!drag || event.pointerId !== drag.id || !anchor.value?.parentElement) {
    return
  }
  const parent = anchor.value.parentElement.getBoundingClientRect()
  const base = anchor.value.getBoundingClientRect()
  const proposedX = drag.ox + event.clientX - drag.x
  const proposedY = drag.oy + event.clientY - drag.y
  const shiftX = proposedX - offset.value.x
  const shiftY = proposedY - offset.value.y
  let left = base.left + shiftX
  let top = base.top + shiftY
  const keep = 72
  if (left + base.width < parent.left + keep) {
    left = parent.left + keep - base.width
  }
  if (left > parent.right - keep) {
    left = parent.right - keep
  }
  if (top + base.height < parent.top + keep) {
    top = parent.top + keep - base.height
  }
  if (top > parent.bottom - keep) {
    top = parent.bottom - keep
  }
  offset.value = {
    x: proposedX + (left - (base.left + shiftX)),
    y: proposedY + (top - (base.top + shiftY)),
  }
}

function onPointerUp(event: PointerEvent): void {
  if (!drag || event.pointerId !== drag.id) {
    return
  }
  drag = null
  dragging.value = false
}

function messageClass(message: MatchMessage): string {
  if (message.kind === 'system') {
    return 'is-system'
  }
  if (message.kind === 'thought') {
    return 'is-self'
  }
  return 'is-other'
}
</script>

<template>
  <Transition name="dock">
    <button v-if="!open" class="dock" type="button" @click="emit('open-list')">
      消息
      <span v-if="unreadTotal" class="dock-badge">{{ unreadTotal > 99 ? '99+' : unreadTotal }}</span>
    </button>
  </Transition>
  <Transition name="phone">
    <div
      v-if="open"
      ref="anchor"
      class="phone-anchor"
      :class="{ 'is-dragging': dragging }"
      :style="{ transform: `translate(${offset.x}px, ${offset.y}px)` }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <section class="phone" aria-label="微信">
        <div class="screen">
          <div class="stage">
            <Transition :name="motion">
              <div :key="page" class="page">
                <header class="nav" :class="{ 'is-dragging': dragging }">
                  <button v-if="page !== 'list'" class="nav-btn" type="button" @click="back">返回</button>
                  <span v-else class="nav-pad"></span>
                  <strong>{{ title }}</strong>
                  <button class="nav-btn" type="button" @click="emit('close')">关闭</button>
                </header>

                <ul v-if="page === 'list'" class="rows">
                  <li v-if="seating">
                    <button class="shuffle" type="button" :disabled="shuffling" @click="emit('shuffle')">
                      {{ shuffling ? '试音中' : '随机模型' }}
                    </button>
                  </li>
                  <li v-for="chat in chats" :key="chat.id">
                    <button class="row" type="button" @click="emit('open-chat', chat.id)">
                      <span class="avatar" :style="{ background: chat.color }">{{ chat.glyph }}</span>
                      <span class="row-copy">
                        <span class="row-title">
                          {{ chat.title }}
                          <em v-if="chat.kind === 'self'">心声</em>
                        </span>
                        <span class="row-preview">{{ preview(chat) }}</span>
                      </span>
                      <span v-if="unread(chat)" class="badge">{{ unread(chat) }}</span>
                    </button>
                  </li>
                </ul>

                <div v-else-if="page === 'thread'" ref="scroller" class="thread" @scroll="onThreadScroll">
                  <div v-if="active?.kind === 'self' && seat && !seating" class="thread-tools">
                    <button type="button" @click="emit('peek')">{{ peeked || '翻开身份' }}</button>
                  </div>
                  <p v-for="message in active?.messages || []" :key="message.id" class="msg" :class="messageClass(message)">
                    <span v-if="message.kind !== 'system' && active?.kind === 'group'" class="who">{{ message.name }}</span>
                    <span class="bubble-text">{{ message.text }}<i v-if="message.streaming" class="caret"></i></span>
                  </p>
                  <p v-if="(active?.messages.length || 0) === 0" class="quiet">还没有消息</p>
                </div>

                <div v-else class="models">
                  <label class="search">
                    <input ref="searchBox" v-model="query" type="search" placeholder="搜索" />
                  </label>
                  <button v-if="seating" class="shuffle" type="button" :disabled="shuffling" @click="emit('shuffle')">
                    {{ shuffling ? '试音中' : '随机模型' }}
                  </button>
                  <ul class="model-list">
                    <li v-for="model in filteredModels" :key="model.id">
                      <button
                        type="button"
                        :disabled="Boolean(probing)"
                        :aria-pressed="seat?.model === model.id"
                        @click="emit('pick-model', model.id)"
                      >
                        <span>{{ model.title }}</span>
                        <em v-if="probing === model.id">试音中</em>
                        <em v-else-if="rejected[model.id]" class="bad">{{ rejected[model.id] }}</em>
                      </button>
                    </li>
                    <li v-if="filteredModels.length === 0" class="quiet">没有这个模型</li>
                  </ul>
                  <template v-if="roles.length">
                    <p class="role-label">身份</p>
                    <div class="roles">
                    <button type="button" :aria-pressed="!seat?.pinned" @click="emit('pick-role', '')">随机</button>
                    <button
                      v-for="role in roles"
                      :key="role.role"
                      type="button"
                      :aria-pressed="seat?.pinned === role.title"
                      @click="emit('pick-role', role.role)"
                    >
                      {{ role.title }}
                    </button>
                  </div>
                  </template>
                </div>
              </div>
            </Transition>
          </div>
        </div>
      </section>
    </div>
  </Transition>
</template>

<style scoped>
.dock {
  position: absolute;
  top: 16px;
  right: 18px;
  z-index: 7;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 14px;
  border: 0;
  border-radius: 18px;
  background: #07c160;
  color: #fff;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 14px;
  cursor: pointer;
}

.dock-enter-active,
.dock-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}

.dock-enter-from,
.dock-leave-to {
  opacity: 0;
  transform: scale(0.92);
}

.dock-badge,
.badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #fa5151;
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}

.phone-anchor {
  position: absolute;
  right: 16px;
  bottom: 88px;
  z-index: 8;
  width: min(360px, calc(100% - 32px));
  height: min(640px, calc(100% - 104px));
}

.phone-anchor.is-dragging {
  z-index: 9;
}

.phone-enter-active .phone,
.phone-leave-active .phone {
  transition:
    opacity 0.24s ease,
    transform 0.34s cubic-bezier(0.32, 0.72, 0, 1);
}

.phone-enter-from .phone,
.phone-leave-to .phone {
  opacity: 0;
  transform: translateY(18px) scale(0.96);
}

.phone-leave-active {
  pointer-events: none;
}

.phone {
  width: 100%;
  height: 100%;
  padding: 8px;
  border-radius: 28px;
  background: #111;
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
}

.screen,
.stage {
  height: 100%;
  overflow: hidden;
  border-radius: 20px;
  background: #ededed;
  color: #111;
  color-scheme: light;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.stage {
  position: relative;
}

.page {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #ededed;
}

.push-enter-active,
.push-leave-active,
.pop-enter-active,
.pop-leave-active {
  transition: transform 0.34s cubic-bezier(0.32, 0.72, 0, 1);
}

.push-enter-from,
.pop-leave-to {
  transform: translateX(100%);
}

.push-leave-to,
.pop-enter-from {
  transform: translateX(-30%);
}

.push-enter-active,
.pop-leave-active {
  z-index: 2;
  box-shadow: -10px 0 18px rgba(0, 0, 0, 0.12);
}

.nav {
  display: grid;
  grid-template-columns: 64px 1fr 64px;
  align-items: center;
  flex: none;
  height: 48px;
  background: #ededed;
  border-bottom: 1px solid #d6d6d6;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.nav.is-dragging {
  cursor: grabbing;
}

.nav strong {
  overflow: hidden;
  font-size: 17px;
  font-weight: 600;
  text-align: center;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.nav-btn,
.nav-pad {
  border: 0;
  background: transparent;
  color: #111;
  font: inherit;
  font-size: 15px;
  cursor: pointer;
}

.nav-pad {
  cursor: grab;
}

.rows,
.thread,
.model-list {
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.rows::-webkit-scrollbar,
.thread::-webkit-scrollbar,
.model-list::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}

.rows,
.model-list {
  list-style: none;
  background: #fff;
}

.row,
.model-list button,
.roles button,
.thread-tools button {
  border: 0;
  background: #fff;
  color: #111;
  font: inherit;
  cursor: pointer;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px 14px;
  text-align: left;
  border-bottom: 1px solid #ededed;
}

.avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 42px;
  height: 42px;
  border-radius: 6px;
  color: #1a1a1a;
  font-size: 16px;
}

.row-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  gap: 4px;
}

.row-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 16px;
}

.row-title em,
.model-list em {
  color: #888;
  font-style: normal;
  font-size: 12px;
}

.row-preview {
  overflow: hidden;
  color: #888;
  font-size: 13px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.thread {
  padding: 12px;
  background: #ededed;
}

.thread-tools {
  display: flex;
  justify-content: center;
  margin-bottom: 10px;
}

.thread-tools button {
  height: 28px;
  padding: 0 12px;
  border-radius: 14px;
  background: #fff;
  color: #576b95;
  font-size: 13px;
}

.msg {
  display: flex;
  flex-direction: column;
  max-width: 78%;
  margin: 0 0 10px;
}

.msg.is-other {
  align-items: flex-start;
}

.msg.is-self {
  align-items: flex-end;
  margin-left: auto;
}

.msg.is-system {
  max-width: none;
  align-items: center;
  margin: 0 0 10px;
}

.who {
  margin-bottom: 2px;
  color: #576b95;
  font-size: 12px;
}

.bubble-text {
  padding: 8px 10px;
  border-radius: 6px;
  background: #fff;
  font-size: 15px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.is-self .bubble-text {
  background: #95ec69;
}

.is-system .bubble-text {
  padding: 2px 8px;
  background: transparent;
  color: #888;
  font-size: 12px;
  text-align: center;
}

.caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  background: #111;
  vertical-align: -2px;
  animation: blink 1s steps(1) infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.models {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
  overflow: hidden;
  background: #ededed;
}

.search {
  padding: 8px 12px;
  background: #ededed;
}

.search input {
  width: 100%;
  height: 32px;
  padding: 0 10px;
  border: 0;
  border-radius: 6px;
  background: #fff;
  color: #111;
  -webkit-text-fill-color: #111;
  caret-color: #111;
  color-scheme: light;
  font: inherit;
}

.search input::placeholder {
  color: #888;
  -webkit-text-fill-color: #888;
}

.shuffle {
  display: block;
  width: calc(100% - 24px);
  height: 36px;
  margin: 8px 12px;
  border: 0;
  border-radius: 6px;
  background: #07c160;
  color: #fff;
  -webkit-text-fill-color: #fff;
  font: inherit;
  font-size: 15px;
  cursor: pointer;
}

.shuffle:disabled {
  cursor: default;
  opacity: 0.6;
}

.rows .shuffle {
  width: calc(100% - 28px);
  margin: 10px 14px;
}

.model-list {
  background: #fff;
}

.model-list button {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 12px 14px;
  text-align: left;
  border-bottom: 1px solid #ededed;
}

.model-list button[aria-pressed='true'] {
  color: #07c160;
}

.model-list .bad {
  color: #fa5151;
}

.role-label {
  margin: 0;
  padding: 10px 14px 4px;
  color: #888;
  font-size: 12px;
}

.roles {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 12px 12px;
}

.roles button {
  height: 30px;
  padding: 0 10px;
  border-radius: 4px;
}

.roles button[aria-pressed='true'] {
  background: #07c160;
  color: #fff;
}

.quiet {
  margin: 0;
  padding: 24px 14px;
  color: #888;
  text-align: center;
}
</style>

<style>
.phone-anchor .rows,
.phone-anchor .thread,
.phone-anchor .model-list {
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.phone-anchor .rows::-webkit-scrollbar,
.phone-anchor .thread::-webkit-scrollbar,
.phone-anchor .model-list::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}
</style>
