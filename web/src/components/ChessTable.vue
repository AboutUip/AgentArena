<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import WeChat from './WeChat.vue'
import {
  ApiError,
  advanceMatchStream,
  createMatch,
  fetchMatch,
  fetchModelChoices,
  startMatch,
  updateSeat,
  type MatchMessage,
  type MatchView,
  type ModelChoice,
  type XiangqiPiece,
} from '../api'

const props = defineProps<{
  moduleId: string
}>()

const match = ref<MatchView | null>(null)
const models = ref<ModelChoice[]>([])
const error = ref('')
const busy = ref(false)
const selected = ref<number | null>(null)
const phoneOpen = ref(false)
const phonePage = ref<'list' | 'thread' | 'models'>('list')
const phoneChat = ref('score')
const probing = ref('')
const shuffling = ref(false)
const rejected = ref<Record<string, string>>({})

const red = computed(() => match.value?.seats.find((seat) => seat.id === 1) ?? null)
const black = computed(() => match.value?.seats.find((seat) => seat.id === 2) ?? null)
const selectedSeat = computed(() => match.value?.seats.find((seat) => seat.id === selected.value) ?? null)
const pieces = computed(() => match.value?.pieces ?? [])
const gavelLabel = computed(() => {
  const current = match.value
  if (!current) {
    return ''
  }
  if (current.canDeal) {
    return '开局'
  }
  if (current.status === 'ended') {
    return current.winner || '下完了'
  }
  return current.call
})
const gavelDisabled = computed(() => {
  const current = match.value
  return !current || busy.value || current.status === 'ended' || (!current.canDeal && !current.canAdvance)
})

const files = [1, 2, 3, 4, 5, 6, 7]
const ranks = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

function at(file: number, rank: number): Record<string, string> {
  return {
    left: `${(file / 8) * 100}%`,
    top: `${((9 - rank) / 9) * 100}%`,
  }
}

function marked(piece: XiangqiPiece): boolean {
  const last = match.value?.lastMove
  if (!last) {
    return false
  }
  return (
    (piece.file === last.fromFile && piece.rank === last.fromRank) ||
    (piece.file === last.toFile && piece.rank === last.toRank)
  )
}

function modelLabel(model: string, title: string): string {
  if (model === 'rehearsal') {
    return '牌桌试音'
  }
  return (model.split('/').pop() || title).replace(/-\d{8}$/, '')
}

function apply(next: MatchView): void {
  match.value = next
}

async function boot(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    apply(await createMatch(props.moduleId))
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '这一盘没有摆开。'
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
  const head = id.toLowerCase().includes('/') ? id.toLowerCase().slice(0, id.indexOf('/')) : id.toLowerCase().split(/[-_.]/)[0]
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

async function shuffleModels(): Promise<void> {
  const current = match.value
  if (!current || current.status !== 'seating' || shuffling.value) {
    return
  }
  const groups = new Map<string, string[]>()
  for (const id of shuffleIds(models.value.map((model) => model.id).filter((id) => id !== 'rehearsal'))) {
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

async function gavel(): Promise<void> {
  const current = match.value
  if (!current || busy.value || current.status === 'ended') {
    return
  }
  busy.value = true
  error.value = ''
  try {
    if (current.canDeal) {
      apply(await startMatch(props.moduleId))
    } else if (current.canAdvance) {
      let done: MatchView | null = null
      let failed = ''
      await advanceMatchStream(props.moduleId, (event) => {
        if (event.event === 'thought' && event.data.chatId && event.data.messageId != null) {
          growThought(event.data.chatId, event.data.messageId, event.data.delta || '', event.data.name || '')
        } else if (event.event === 'error') {
          failed = event.data.detail || '这一步没有走下去。'
        } else if (event.event === 'done') {
          done = event.data as MatchView
        }
      })
      if (failed) {
        error.value = failed
        apply(await fetchMatch(props.moduleId))
      } else if (done) {
        apply(done)
      }
    }
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '这一步没有走下去。'
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  void boot()
  void fetchModelChoices().then((items) => {
    models.value = [{ id: 'rehearsal', title: '牌桌试音' }, ...items.filter((item) => item.id !== 'rehearsal')]
  })
})
</script>

<template>
  <div class="room">
    <button v-if="black" class="player" type="button" :class="{ live: match?.speaking === black.id }" @click="onSeat(black.id)">
      <span class="seal">将</span>
      <span>
        <strong>黑方</strong>
        <em>{{ modelLabel(black.model, black.modelTitle) }}</em>
      </span>
    </button>

    <div class="board" aria-label="棋盘">
      <div class="field">
        <svg class="grid" viewBox="0 0 8 9" preserveAspectRatio="none" aria-hidden="true">
          <line x1="0" y1="0" x2="0" y2="9" />
          <line x1="8" y1="0" x2="8" y2="9" />
          <line v-for="file in files" :key="`u${file}`" :x1="file" y1="0" :x2="file" y2="4" />
          <line v-for="file in files" :key="`d${file}`" :x1="file" y1="5" :x2="file" y2="9" />
          <line v-for="rank in ranks" :key="`h${rank}`" x1="0" :y1="rank" x2="8" :y2="rank" />
          <line x1="3" y1="7" x2="5" y2="9" />
          <line x1="5" y1="7" x2="3" y2="9" />
          <line x1="3" y1="0" x2="5" y2="2" />
          <line x1="5" y1="0" x2="3" y2="2" />
        </svg>
        <p class="river"><span>楚河</span><span>汉界</span></p>
        <i
          v-if="match?.lastMove"
          class="trace"
          :style="at(match.lastMove.fromFile, match.lastMove.fromRank)"
        />
        <i
          v-if="match?.lastMove"
          class="trace"
          :style="at(match.lastMove.toFile, match.lastMove.toRank)"
        />
        <span
          v-for="piece in pieces"
          :key="`${piece.file}-${piece.rank}`"
          class="piece"
          :class="[piece.side, { moved: marked(piece) }]"
          :style="at(piece.file, piece.rank)"
        >
          {{ piece.label }}
        </span>
      </div>
    </div>

    <button v-if="red" class="player" type="button" :class="{ live: match?.speaking === red.id }" @click="onSeat(red.id)">
      <span class="seal red">帅</span>
      <span>
        <strong>红方</strong>
        <em>{{ modelLabel(red.model, red.modelTitle) }}</em>
      </span>
    </button>

    <p v-if="error" class="note" role="alert">{{ error }}</p>
    <div class="hand">
      <button class="gavel" type="button" :disabled="gavelDisabled" @click="gavel">
        {{ busy && match?.status === 'playing' ? '还在想。' : gavelLabel }}
      </button>
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
      peeked=""
      @close="phoneOpen = false"
      @open-list="phoneOpen = true; phonePage = 'list'"
      @open-chat="openChat"
      @open-models="phonePage = 'models'"
      @pick-model="changeModel"
      @shuffle="shuffleModels"
      @pick-role="() => {}"
      @peek="() => {}"
    />
  </div>
</template>

<style scoped>
.room {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  min-height: 0;
  padding: 28px 24px 92px;
  color: #f4e7cf;
}

.player {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 220px;
  padding: 8px 14px;
  border: 1px solid rgba(244, 231, 207, 0.18);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
  color: inherit;
  cursor: pointer;
}

.player strong,
.player em {
  display: block;
  font-style: normal;
}

.player em {
  color: rgba(244, 231, 207, 0.62);
  font-size: 13px;
}

.player.live {
  border-color: #e7c27a;
}

.seal {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border: 1px solid #1c1c1c;
  border-radius: 50%;
  background: #f6e7c8;
  color: #1c1c1c;
  font-family: 'Songti SC', 'Source Han Serif SC', serif;
}

.seal.red {
  border-color: #9c2b1b;
  color: #9c2b1b;
}

.board {
  padding: 18px;
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.16), transparent 28%),
    #d7b06a;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.28);
}

.field {
  position: relative;
  width: min(440px, calc(100vw - 96px));
  aspect-ratio: 8 / 9;
}

.grid {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  stroke: #5c3b22;
  stroke-width: 0.045;
  fill: none;
}

.river {
  position: absolute;
  top: 50%;
  right: 8%;
  left: 8%;
  display: flex;
  justify-content: space-between;
  margin: 0;
  color: #6d4b28;
  font-family: 'Songti SC', 'Source Han Serif SC', serif;
  letter-spacing: 0.4em;
  transform: translateY(-50%);
  pointer-events: none;
}

.piece,
.trace {
  position: absolute;
  transform: translate(-50%, -50%);
}

.trace {
  width: 12%;
  aspect-ratio: 1;
  border: 2px solid rgba(156, 43, 27, 0.85);
  border-radius: 4px;
  pointer-events: none;
}

.piece {
  display: grid;
  width: 11.5%;
  aspect-ratio: 1;
  place-items: center;
  border: 2px solid #1c1c1c;
  border-radius: 50%;
  background:
    radial-gradient(circle at 35% 30%, #fff8ea, #f0ddb4 62%, #e4c890);
  color: #1c1c1c;
  font-family: 'Songti SC', 'Source Han Serif SC', serif;
  font-size: clamp(16px, 2.4vw, 22px);
  line-height: 1;
  box-shadow: 0 2px 0 rgba(92, 59, 34, 0.25);
}

.piece.red {
  border-color: #9c2b1b;
  color: #9c2b1b;
}

.piece.moved {
  box-shadow: 0 0 0 3px rgba(156, 43, 27, 0.28);
}

.note {
  margin: 0;
  color: #f0c7b2;
}

.hand {
  position: absolute;
  bottom: 22px;
  z-index: 9;
}

.gavel {
  height: 44px;
  padding: 0 22px;
  border: 0;
  border-radius: 999px;
  background: #f4e7cf;
  color: #3a2415;
  font: inherit;
  cursor: pointer;
}

.gavel:disabled {
  cursor: default;
  opacity: 0.55;
}

.gavel:focus-visible,
.player:focus-visible {
  outline: 2px solid #f4e7cf;
  outline-offset: 3px;
}

@media (max-width: 720px) {
  .room {
    gap: 12px;
    padding-right: 16px;
    padding-left: 16px;
  }

  .field {
    width: min(440px, calc(100vw - 64px));
  }
}
</style>
