<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import WeChat from './WeChat.vue'
import {
  ApiError,
  advanceMatchStream,
  createMatch,
  fetchMatch,
  fetchModelChoices,
  peekSeat,
  startMatch,
  updateSeat,
  type MatchMessage,
  type MatchView,
  type ModelChoice,
} from '../api'
import { playDay, playNight, playSpeak, playWolf, setSoundMuted, soundMuted, soundsPlayed } from '../game/sound'
import { mountTable, seatAnchor, type TableHandle } from '../game/table'

const props = defineProps<{
  moduleId: string
}>()

const match = ref<MatchView | null>(null)
const error = ref('')
const busy = ref(false)
const host = ref<HTMLElement | null>(null)
const stage = ref<HTMLElement | null>(null)
const size = ref({ width: 800, height: 600 })
const selected = ref<number | null>(null)
const phoneOpen = ref(false)
const phonePage = ref<'list' | 'thread' | 'models'>('list')
const phoneChat = ref('public')
const peeked = ref<Record<number, string>>({})
const models = ref<ModelChoice[]>([{ id: 'rehearsal', title: '牌桌试音' }])
const probing = ref('')
const shuffling = ref(false)
const rejected = ref<Record<string, string>>({})
const muted = ref(soundMuted())
let table: TableHandle | null = null
let observer: ResizeObserver | null = null

const slots = computed(() => {
  const current = match.value
  if (!current) {
    return []
  }
  return current.seats.map((seat, index) => ({
    index,
    seat,
    point: seatAnchor(index, current.seats.length, size.value.width, size.value.height),
  }))
})

const gavelLabel = computed(() => {
  const current = match.value
  if (!current) {
    return '摆桌子'
  }
  if (current.canDeal) {
    return '发牌'
  }
  return current.call
})

const gavelDisabled = computed(() => {
  const current = match.value
  if (!current || busy.value || current.status === 'ended') {
    return true
  }
  return !current.canDeal && !current.canAdvance
})

const selectedSeat = computed(() => match.value?.seats.find((seat) => seat.id === selected.value) ?? null)

const sky = computed(() => {
  const current = match.value
  if (!current || current.status === 'seating') {
    return 'day'
  }
  if (current.scene === 'wolf_room') {
    return 'wolf'
  }
  if (current.phase === 'night') {
    return 'night'
  }
  return 'day'
})

function modelLabel(model: string, title: string): string {
  if (model === 'rehearsal') {
    return '牌桌试音'
  }
  const leaf = (model.split('/').pop() || title).replace(/-\d{8}$/, '')
  return leaf
}

function openChat(id: string): void {
  phoneOpen.value = true
  phoneChat.value = id
  phonePage.value = 'thread'
  if (id.startsWith('mind:')) {
    const seatId = Number(id.slice(5))
    if (seatId) {
      selected.value = seatId
    }
  }
}

function showList(): void {
  phoneOpen.value = true
  phonePage.value = 'list'
}

function roleLine(seatId: number, exposedRole: string): string {
  return peeked.value[seatId] || exposedRole
}

function paint(): void {
  const current = match.value
  if (!current || !table) {
    return
  }
  const scene = current.scene === 'wolf_room' ? 'wolf_room' : current.phase
  table.paint({
    scene,
    count: current.seats.length,
    seats: current.seats.map((seat, index) => ({
      index,
      speaking: seat.speaking,
      alive: seat.alive,
    })),
  })
  window.__arena = {
    call: current.call,
    status: current.status,
    scene: current.scene,
    phase: current.phase,
    winner: current.winner,
    banner: current.banner,
    sounds: soundsPlayed(),
  }
}

function cue(previous: MatchView | null, next: MatchView): void {
  if (!previous) {
    return
  }
  if (previous.scene !== 'wolf_room' && next.scene === 'wolf_room') {
    playWolf()
  } else if (previous.phase !== next.phase && (next.phase === 'night' || next.scene === 'wolf_room')) {
    playNight()
  } else if (previous.phase !== next.phase && (next.phase === 'day' || next.phase === 'end')) {
    playDay()
  } else if (next.bubble?.text && next.bubble.text !== previous.bubble?.text) {
    playSpeak()
  }
  paint()
}

function apply(next: MatchView, audible = false): void {
  const previous = match.value
  match.value = next
  if (selected.value != null && !next.seats.some((seat) => seat.id === selected.value)) {
    selected.value = null
  }
  if (audible) {
    cue(previous, next)
  } else {
    paint()
  }
}

async function boot(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    apply(await createMatch(props.moduleId))
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '这一桌没有摆开。'
  } finally {
    busy.value = false
  }
}

function onSeat(seatId: number): void {
  const current = match.value
  if (!current) {
    return
  }
  selected.value = seatId
  phoneOpen.value = true
  if (current.status === 'seating') {
    phonePage.value = 'models'
    return
  }
  phoneChat.value = `mind:${seatId}`
  phonePage.value = 'thread'
}

async function changeModel(model: string): Promise<void> {
  if (selected.value == null || probing.value || shuffling.value) {
    return
  }
  probing.value = model
  try {
    apply(await updateSeat(props.moduleId, selected.value, { model }))
    const next = { ...rejected.value }
    delete next[model]
    rejected.value = next
  } catch (caught) {
    const message = caught instanceof ApiError ? caught.message : '无效'
    rejected.value = { ...rejected.value, [model]: message }
  } finally {
    probing.value = ''
  }
}

const PROVIDERS: Record<string, string> = {
  moonshotai: 'kimi',
  kimi: 'kimi',
  qwen: 'qwen',
  alibaba: 'qwen',
  doubao: 'doubao',
  volcengine: 'doubao',
  deepseek: 'deepseek',
  'z-ai': 'zhipu',
  zhipu: 'zhipu',
  glm: 'zhipu',
  openai: 'openai',
  anthropic: 'anthropic',
  google: 'google',
  gemini: 'google',
  meituan: 'meituan',
  longcat: 'meituan',
}

function providerOf(id: string): string {
  const lower = id.toLowerCase()
  const head = lower.includes('/') ? lower.slice(0, lower.indexOf('/')) : lower.split(/[-_.]/)[0]
  const brand = head.replace(/\d+$/, '')
  return PROVIDERS[brand] || brand
}

function shuffleIds(ids: string[]): string[] {
  const copy = [...ids]
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(Math.random() * (index + 1))
    const current = copy[index]
    copy[index] = copy[swap]
    copy[swap] = current
  }
  return copy
}

function diverseModels(ids: string[]): string[] {
  const groups = new Map<string, string[]>()
  for (const id of shuffleIds(ids)) {
    const key = providerOf(id)
    const bucket = groups.get(key)
    if (bucket) {
      bucket.push(id)
    } else {
      groups.set(key, [id])
    }
  }
  const buckets = shuffleIds([...groups.keys()]).map((key) => groups.get(key) || [])
  const queue: string[] = []
  let pending = true
  while (pending) {
    pending = false
    for (const bucket of buckets) {
      const id = bucket.pop()
      if (!id) {
        continue
      }
      queue.push(id)
      pending = true
    }
  }
  return queue
}

async function shuffleModels(): Promise<void> {
  const current = match.value
  if (!current || current.status !== 'seating' || shuffling.value) {
    return
  }
  const queue = diverseModels(models.value.map((model) => model.id).filter((id) => id !== 'rehearsal'))
  if (queue.length === 0) {
    error.value = '没有可以试的模型。'
    return
  }
  shuffling.value = true
  error.value = ''
  let cursor = 0
  try {
    for (const seat of current.seats) {
      let placed = false
      while (cursor < queue.length) {
        const modelId = queue[cursor]
        cursor += 1
        probing.value = modelId
        try {
          apply(await updateSeat(props.moduleId, seat.id, { model: modelId }))
          const next = { ...rejected.value }
          delete next[modelId]
          rejected.value = next
          placed = true
          break
        } catch (caught) {
          const message = caught instanceof ApiError ? caught.message : '无效'
          rejected.value = { ...rejected.value, [modelId]: message }
          if (message === '这个座位还连不上模型。') {
            error.value = message
            return
          }
        }
      }
      if (!placed) {
        error.value = `${seat.name}没有找到有效模型。`
        return
      }
    }
  } finally {
    probing.value = ''
    shuffling.value = false
  }
}

async function changeRole(role: string): Promise<void> {
  if (selected.value == null || shuffling.value) {
    return
  }
  try {
    apply(await updateSeat(props.moduleId, selected.value, { role: role || null, clearRole: role === '' }))
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '身份没有改成。'
  }
}

async function togglePeek(): Promise<void> {
  const seat = selectedSeat.value
  if (!seat || !match.value || match.value.status === 'seating') {
    return
  }
  if (peeked.value[seat.id]) {
    const next = { ...peeked.value }
    delete next[seat.id]
    peeked.value = next
    return
  }
  try {
    const body = await peekSeat(props.moduleId, seat.id)
    if (body.role) {
      peeked.value = { ...peeked.value, [seat.id]: body.role }
    }
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '这一张牌翻不开。'
  }
}

async function gavel(): Promise<void> {
  const current = match.value
  if (!current || busy.value || current.status === 'ended') {
    return
  }
  busy.value = true
  error.value = ''
  try {
    if (current.canDeal) {
      peeked.value = {}
      apply(await startMatch(props.moduleId), true)
      phoneOpen.value = true
      phonePage.value = 'list'
    } else if (current.canAdvance) {
      let done: MatchView | null = null
      let failed = ''
      await advanceMatchStream(props.moduleId, (event) => {
        if (event.event === 'thought' && event.data.chatId && event.data.messageId != null) {
          growThought(event.data.chatId, event.data.messageId, event.data.delta || '', event.data.name || '')
        } else if (event.event === 'error') {
          failed = event.data.detail || '这一拍没有走下去。'
        } else if (event.event === 'done') {
          done = event.data as MatchView
        }
      })
      if (failed) {
        error.value = failed
        apply(await fetchMatch(props.moduleId))
      } else if (done) {
        apply(done, true)
      }
    }
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '这一拍没有走下去。'
  } finally {
    busy.value = false
    paint()
  }
}

function growThought(chatId: string, messageId: number, delta: string, name: string): void {
  const current = match.value
  if (!current) {
    return
  }
  const chat = current.chats.find((item) => item.id === chatId)
  if (!chat) {
    return
  }
  let message = chat.messages.find((item) => item.id === messageId)
  if (!message) {
    const seat = current.seats.find((item) => item.name === name)
    message = {
      id: messageId,
      kind: 'thought',
      seatId: seat?.id ?? null,
      name,
      glyph: seat?.mark.glyph || '',
      text: '',
      streaming: true,
    } satisfies MatchMessage
    chat.messages.push(message)
  }
  message.text += delta
  message.streaming = true
}

function toggleSound(): void {
  muted.value = !muted.value
  setSoundMuted(muted.value)
}

onMounted(() => {
  if (stage.value) {
    table = mountTable(stage.value)
  }
  if (host.value) {
    const measure = (): void => {
      size.value = {
        width: host.value?.clientWidth || 800,
        height: host.value?.clientHeight || 600,
      }
      table?.resize()
      paint()
    }
    observer = new ResizeObserver(measure)
    observer.observe(host.value)
    measure()
  }
  void boot()
  void fetchModelChoices().then((items) => {
    models.value = [{ id: 'rehearsal', title: '牌桌试音' }, ...items.filter((item) => item.id !== 'rehearsal')]
  })
})

onBeforeUnmount(() => {
  observer?.disconnect()
  table?.destroy()
  delete window.__arena
})
</script>

<template>
  <div class="felt" :data-scene="match?.scene === 'wolf_room' ? 'wolf_room' : match?.phase">
    <div ref="host" class="board">
    <div ref="stage" class="felt-canvas"></div>
    <div class="sky" :data-sky="sky">
      <span class="orb" aria-hidden="true"></span>
      <button class="mute" type="button" :aria-pressed="muted" :aria-label="muted ? '打开声音' : '关掉声音'" @click="toggleSound">
        {{ muted ? '静' : '声' }}
      </button>
    </div>
    <p v-if="match" class="felt-banner" :class="{ 'is-end': match.status === 'ended' }">{{ match.banner }}</p>
    <button
      v-for="slot in slots"
      :key="slot.seat.id"
      class="token"
      :class="{
        'is-speaking': slot.seat.speaking,
        'is-out': !slot.seat.alive,
        'is-selected': slot.seat.id === selected && phoneOpen,
      }"
      :style="{ left: `${slot.point.x}px`, top: `${slot.point.y}px` }"
      :aria-pressed="slot.seat.id === selected && phoneOpen"
      :title="slot.seat.modelTitle"
      @click="onSeat(slot.seat.id)"
    >
      <span class="token-mark" :style="{ background: slot.seat.mark.color }">{{ slot.seat.mark.glyph }}</span>
      <span class="token-name">{{ slot.seat.name }}</span>
      <span class="token-model">{{ modelLabel(slot.seat.model, slot.seat.modelTitle) }}</span>
      <span v-if="roleLine(slot.seat.id, slot.seat.exposedRole)" class="token-role">
        {{ roleLine(slot.seat.id, slot.seat.exposedRole) }}
      </span>
      <span v-else-if="match?.status === 'seating' && slot.seat.pinned" class="token-role">{{ slot.seat.pinned }}</span>
    </button>
    <p v-if="error" class="felt-error" role="alert">{{ error }}</p>
    <div class="felt-hand">
      <button class="gavel" :class="{ 'is-over': match?.status === 'ended' }" type="button" :disabled="gavelDisabled" @click="gavel">
        {{ busy && match?.status === 'playing' ? '还在听。' : gavelLabel }}
      </button>
    </div>
    </div>
    <WeChat
      v-if="match"
      :open="phoneOpen"
      :page="phonePage"
      :chat-id="phoneChat"
      :chats="match.chats"
      :models="models"
      :roles="match.roles"
      :seat="selectedSeat"
      :seating="match.status === 'seating'"
      :probing="probing"
      :shuffling="shuffling"
      :rejected="rejected"
      :peeked="selectedSeat ? roleLine(selectedSeat.id, selectedSeat.exposedRole) : ''"
      @close="phoneOpen = false"
      @open-list="showList"
      @open-chat="openChat"
      @open-models="phonePage = 'models'"
      @pick-model="changeModel"
      @pick-role="changeRole"
      @shuffle="shuffleModels"
      @peek="togglePeek"
    />
  </div>
</template>

<style scoped>
.felt {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  color: #f3ecdf;
  background: #14110e;
}

.board {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.felt-canvas {
  position: absolute;
  inset: 0;
}

.felt-canvas :deep(canvas) {
  display: block;
}

.sky {
  position: absolute;
  top: 16px;
  left: 18px;
  z-index: 6;
  display: flex;
  align-items: center;
  gap: 8px;
}

.orb {
  position: relative;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #e7c9a1;
  box-shadow:
    0 0 0 6px rgba(231, 201, 161, 0.18),
    0 0 18px rgba(231, 201, 161, 0.45);
}

.sky[data-sky='night'] .orb,
.sky[data-sky='wolf'] .orb {
  background: #f4e7c5;
  box-shadow: 0 0 16px rgba(244, 231, 197, 0.4);
}

.sky[data-sky='night'] .orb::after,
.sky[data-sky='wolf'] .orb::after {
  content: '';
  position: absolute;
  top: -2px;
  left: 10px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #14110e;
}

.sky[data-sky='wolf'] .orb {
  background: #e7b2a8;
  box-shadow: 0 0 16px rgba(140, 58, 58, 0.55);
}

.sky[data-sky='wolf'] .orb::after {
  background: #3a1818;
}

.mute,
.sheet button,
.gavel,
.peek {
  border: 1px solid #d7b56d;
  background: #2a2118;
  color: #f4e7c5;
  font-family: 'Source Sans 3', 'Songti SC', serif;
  cursor: pointer;
}

.mute {
  width: 32px;
  height: 32px;
  border-radius: 50%;
}

.felt-banner {
  position: absolute;
  top: 46%;
  left: 50%;
  z-index: 2;
  width: min(280px, 34%);
  margin: 0;
  transform: translate(-50%, -50%);
  color: #f4e7c5;
  font-family: 'Source Sans 3', 'Songti SC', serif;
  font-size: 22px;
  line-height: 1.45;
  text-align: center;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.45);
  pointer-events: none;
}

.felt-banner.is-end {
  font-size: 28px;
}

.bubble {
  position: absolute;
  z-index: 4;
  width: 180px;
  margin: 0;
  transform: translate(-50%, -50%);
  pointer-events: none;
}

.bubble.speech {
  padding: 10px 12px;
  border: 1px solid #d7b56d;
  border-radius: 16px 16px 16px 6px;
  background: #f3ecdf;
  color: #1a120e;
}

.bubble.thought {
  padding: 8px 10px;
  border: 1px dashed rgba(244, 231, 197, 0.7);
  border-radius: 18px;
  background: rgba(20, 17, 14, 0.72);
  color: #f4e7c5;
  font-size: 13px;
}

.bubble-who {
  display: block;
  margin-bottom: 4px;
  color: #6b3e2a;
  font-size: 12px;
}

.bubble p,
.line-thought,
.line-speech {
  margin: 0;
  line-height: 1.4;
}

.bubble-note {
  margin-top: 6px;
  color: #6b3e2a;
  font-size: 13px;
}

.token {
  position: absolute;
  z-index: 3;
  display: flex;
  width: 108px;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: #f3ecdf;
  transform: translate(-50%, -50%);
  cursor: pointer;
}

.token:focus-visible,
.mute:focus-visible,
.gavel:focus-visible,
.sheet button:focus-visible,
.search input:focus-visible {
  outline: 2px solid #f4e7c5;
  outline-offset: 2px;
}

.token-mark {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border: 2px solid #d7b56d;
  border-radius: 50%;
  color: #1a120e;
  font-size: 18px;
  font-weight: 600;
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.28);
}

.token-name {
  max-width: 108px;
  font-size: 13px;
  line-height: 1.2;
}

.token-model,
.token-role {
  max-width: 108px;
  color: #d7b56d;
  font-size: 11px;
  line-height: 1.25;
  text-align: center;
  word-break: break-all;
}

.token.is-speaking .token-mark {
  box-shadow: 0 0 0 4px rgba(215, 181, 109, 0.45);
}

.token.is-out {
  opacity: 0.72;
}

.token.is-out .token-mark {
  filter: grayscale(1);
  box-shadow: none;
}

.token.is-selected .token-name {
  color: #d7b56d;
}

.felt-hand {
  position: absolute;
  bottom: 22px;
  left: 50%;
  z-index: 9;
  transform: translateX(-50%);
}

.gavel {
  min-width: 220px;
  padding: 12px 22px;
  border-radius: 999px;
  font-size: 18px;
}

.gavel:disabled {
  cursor: default;
  opacity: 0.55;
}

.gavel.is-over:disabled {
  opacity: 1;
}

.felt-error {
  position: absolute;
  bottom: 76px;
  left: 50%;
  z-index: 5;
  max-width: min(420px, 80%);
  margin: 0;
  color: #f0c7c0;
  text-align: center;
  transform: translateX(-50%);
}

.sheet {
  display: flex;
  flex: none;
  width: min(340px, 42%);
  flex-direction: column;
  padding: 14px;
  border-left: 1px solid #d7b56d;
  background: #1c1612;
}

.sheet-head,
.sheet-head div {
  display: flex;
  gap: 8px;
}

.sheet-head {
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.sheet-head div {
  flex-direction: column;
  min-width: 0;
}

.sheet-head strong {
  font-size: 20px;
}

.sheet-head span {
  color: #d7b56d;
  font-size: 13px;
  word-break: break-all;
}

.sheet-head button,
.peek {
  padding: 6px 12px;
  border-radius: 999px;
}

.search {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
  color: #cbb89a;
  font-size: 13px;
}

.search input {
  padding: 8px 10px;
  border: 1px solid #6b3e2a;
  border-radius: 10px;
  background: #14110e;
  color: #f3ecdf;
  font: inherit;
}

.choices,
.lines {
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: auto;
  list-style: none;
}

.choices {
  flex: 1;
}

.choices.roles {
  flex: none;
  max-height: 132px;
}

.choices button,
.lines li {
  width: 100%;
}

.choices button {
  width: 100%;
  margin-bottom: 4px;
  padding: 8px 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #f3ecdf;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.choices button[aria-pressed='true'] {
  background: #3a2a1c;
  color: #f4e7c5;
}

.sheet-label {
  margin: 10px 0 6px;
  color: #d7b56d;
  font-size: 13px;
}

.peek {
  margin-bottom: 10px;
}

.lines {
  flex: 1;
}

.lines li {
  margin-bottom: 12px;
}

.line-thought {
  margin-bottom: 4px;
  padding: 8px 10px;
  border: 1px dashed rgba(244, 231, 197, 0.55);
  border-radius: 14px;
  color: #f4e7c5;
}

.line-speech {
  padding: 8px 10px;
  border-radius: 14px 14px 14px 4px;
  background: #f3ecdf;
  color: #1a120e;
}

.empty {
  color: #cbb89a;
}

@media (max-width: 720px) {
  .felt {
    flex-direction: column;
  }
  .token {
    width: 72px;
  }

  .token-mark {
    width: 40px;
    height: 40px;
  }

  .felt-banner,
  .bubble {
    width: 150px;
  }

  .sheet {
    width: 100%;
    height: 42%;
    border-left: 0;
    border-top: 1px solid #d7b56d;
  }
}

@media (prefers-reduced-motion: reduce) {
  .token,
  .gavel,
  .felt-banner,
  .bubble {
    transition: none;
  }
}
</style>
