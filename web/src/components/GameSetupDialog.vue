<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ApiError,
  fetchGameSetup,
  saveGameSetup,
  type GameSetup,
  type SetupOption,
} from '../api'

const props = defineProps<{
  moduleId: string
}>()

const emit = defineEmits<{
  leave: []
  start: []
}>()

const setup = ref<GameSetup | null>(null)
const modeId = ref('')
const choices = ref<Record<string, string>>({})
const advanced = ref(false)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const dialog = ref<HTMLElement | null>(null)
const head = ref<HTMLElement | null>(null)
const body = ref<HTMLElement | null>(null)
const foot = ref<HTMLElement | null>(null)
let sizeObserver: ResizeObserver | null = null
let sizeReady = false
let lastHeight = -1

const currentMode = computed(() => setup.value?.modes.find((item) => item.id === modeId.value) ?? null)

const visibleOptions = computed(() => {
  if (!setup.value) {
    return []
  }
  return setup.value.options.filter((option) => applies(option.modes, modeId.value))
})

const groups = computed(() => {
  if (!setup.value) {
    return []
  }
  return setup.value.groups
    .map((group) => ({
      ...group,
      options: visibleOptions.value.filter((option) => option.group === group.id),
    }))
    .filter((group) => group.options.length > 0)
})

onMounted(() => {
  bindSize()
  window.addEventListener('resize', onResize)
  void load()
})

onUnmounted(() => {
  sizeObserver?.disconnect()
  window.removeEventListener('resize', onResize)
})

watch([advanced, modeId, loading], () => {
  void nextTick(() => writeSize(true))
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const body = await fetchGameSetup(props.moduleId)
    setup.value = body
    const savedMode = body.selection?.mode
    modeId.value = body.modes.some((item) => item.id === savedMode) ? savedMode! : (body.modes[0]?.id ?? '')
    choices.value = { ...(body.selection?.choices ?? {}) }
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '无法读取开局配置。'
  } finally {
    loading.value = false
    await nextTick()
    writeSize(true)
  }
}

function heightCap(): number {
  return Math.min(640, window.innerHeight - 128)
}

function writeSize(animate: boolean): void {
  const shell = dialog.value
  const top = head.value
  const middle = body.value
  const bottom = foot.value
  if (!shell || !top || !middle || !bottom) {
    return
  }
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const shellStyles = getComputedStyle(shell)
  const borderY = parseFloat(shellStyles.borderTopWidth) + parseFloat(shellStyles.borderBottomWidth)
  const next = Math.round(Math.min(heightCap(), top.offsetHeight + middle.scrollHeight + bottom.offsetHeight + borderY))
  if (lastHeight >= 0 && Math.abs(next - lastHeight) < 2) {
    return
  }
  const previous = shell.offsetHeight
  lastHeight = next
  if (!animate || reduce || !sizeReady) {
    shell.classList.remove('is-sized')
    shell.style.height = `${next}px`
    if (sizeReady && !reduce) {
      requestAnimationFrame(() => {
        dialog.value?.classList.add('is-sized')
      })
    }
    return
  }
  shell.classList.remove('is-sized')
  shell.style.height = `${previous}px`
  void shell.offsetHeight
  shell.classList.add('is-sized')
  shell.style.height = `${next}px`
}

function bindSize(): void {
  writeSize(false)
  const middle = body.value
  if (!middle) {
    return
  }
  requestAnimationFrame(() => {
    dialog.value?.classList.add('is-sized')
    sizeReady = true
  })
  sizeObserver = new ResizeObserver(() => {
    writeSize(true)
  })
  sizeObserver.observe(middle)
}

function onResize(): void {
  writeSize(true)
}

function applies(modes: string[], mode: string): boolean {
  return modes.length === 0 || modes.includes(mode)
}

function visibleChoices(option: SetupOption) {
  return option.choices.filter((choice) => applies(choice.modes, modeId.value))
}

function selectedChoice(option: SetupOption): string {
  const raw = choices.value[option.id]
  if (raw && visibleChoices(option).some((choice) => choice.id === raw)) {
    return raw
  }
  return option.default
}

function chooseMode(id: string): void {
  modeId.value = id
  error.value = ''
}

function chooseOption(option: SetupOption, choiceId: string): void {
  choices.value = { ...choices.value, [option.id]: choiceId }
  error.value = ''
}

function rosterLine(mode: NonNullable<typeof currentMode.value>): string {
  return mode.roster
    .map((seat) => (seat.count > 1 ? `${seat.role} ×${seat.count}` : seat.role))
    .join('、')
}

async function start(): Promise<void> {
  if (!setup.value || !modeId.value || saving.value) {
    return
  }
  const payload: Record<string, string> = { ...choices.value }
  for (const option of setup.value.options) {
    if (applies(option.modes, modeId.value)) {
      payload[option.id] = selectedChoice(option)
    }
  }
  saving.value = true
  error.value = ''
  try {
    await saveGameSetup(props.moduleId, { mode: modeId.value, choices: payload })
    emit('start')
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '开局配置没有保存。'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="backdrop">
    <div
      ref="dialog"
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="setup-title"
    >
      <div ref="head" class="head">
        <h2 id="setup-title">选择模式</h2>
        <button class="close" type="button" aria-label="返回" @click="emit('leave')">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="currentColor"
              d="M6.7 5.3a1 1 0 0 0-1.4 1.4L10.58 12l-5.3 5.3a1 1 0 1 0 1.42 1.4L12 13.42l5.3 5.3a1 1 0 0 0 1.4-1.42L13.42 12l5.3-5.3a1 1 0 0 0-1.42-1.4L12 10.58l-5.3-5.28z"
            />
          </svg>
        </button>
      </div>

      <div ref="body" class="body">
        <p v-if="loading" class="copy">正在读取规则。</p>
        <p v-else-if="setup && setup.modes.length === 0" class="copy">这个模块还没有可选模式。</p>
        <template v-else-if="setup">
          <div class="modes" role="radiogroup" aria-label="模式">
            <button
              v-for="mode in setup.modes"
              :key="mode.id"
              class="mode"
              type="button"
              role="radio"
              :aria-checked="modeId === mode.id"
              @click="chooseMode(mode.id)"
            >
              <span class="mode-top">
                <span class="mode-title">{{ mode.title }}</span>
                <span class="mode-meta">{{ mode.players }} 人 · {{ mode.win }}</span>
              </span>
              <span class="mode-roster">{{ rosterLine(mode) }}</span>
              <span v-if="mode.nightOrder.length" class="mode-night">夜间 {{ mode.nightOrder.join(' → ') }}</span>
            </button>
          </div>

          <button
            v-if="groups.length"
            class="advanced"
            type="button"
            :aria-expanded="advanced"
            aria-controls="setup-options"
            @click="advanced = !advanced"
          >
            高级设置
          </button>

          <div v-if="advanced" id="setup-options" class="options">
            <section v-for="group in groups" :key="group.id" class="group">
              <h3>{{ group.title }}</h3>
              <div v-for="option in group.options" :key="option.id" class="option">
                <div class="option-copy">
                  <p class="option-title">{{ option.title }}</p>
                  <p class="copy">{{ option.detail }}</p>
                </div>
                <div class="choices" role="radiogroup" :aria-label="option.title">
                  <button
                    v-for="choice in visibleChoices(option)"
                    :key="choice.id"
                    class="choice"
                    type="button"
                    role="radio"
                    :aria-checked="selectedChoice(option) === choice.id"
                    @click="chooseOption(option, choice.id)"
                  >
                    {{ choice.title }}
                  </button>
                </div>
              </div>
            </section>
          </div>
        </template>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
      </div>

      <div ref="foot" class="foot">
        <button class="button" type="button" @click="emit('leave')">返回</button>
        <button class="button primary" type="button" :disabled="loading || saving || !modeId" @click="start">
          {{ saving ? '保存中' : '进入对局' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  z-index: 30;
  top: 64px;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(0, 0, 0, 0.48);
}

.backdrop.setup-enter-active {
  animation: setup-backdrop-in 520ms linear both;
}

.backdrop.setup-leave-active {
  animation: setup-backdrop-out 240ms ease both;
}

.dialog {
  display: flex;
  flex-direction: column;
  width: min(720px, 100%);
  max-height: calc(100dvh - 96px);
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel);
  color: var(--ink);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.24);
}

.dialog.is-sized {
  transition: height 480ms cubic-bezier(0.22, 1.28, 0.36, 1);
}

.setup-enter-active .dialog {
  animation: setup-dialog-in 520ms cubic-bezier(0.22, 1.28, 0.36, 1) both;
}

.setup-leave-active .dialog {
  animation: setup-dialog-out 240ms cubic-bezier(0.4, 0, 1, 1) both;
}

.head,
.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: none;
  padding: 16px 24px;
}

.head {
  min-height: 64px;
  border-bottom: 1px solid var(--line);
}

.foot {
  justify-content: flex-end;
  border-top: 1px solid var(--line);
}

h2,
h3,
.option-title,
.copy,
.notice,
.mode-roster,
.mode-night,
.mode-meta {
  margin: 0;
}

h2 {
  font-size: 20px;
  font-weight: 600;
  line-height: 28px;
}

h3 {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
}

.body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
  padding: 16px 24px 24px;
  overflow: auto;
}

.modes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mode {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease;
}

.mode:hover {
  background: var(--nav-hover);
}

.mode:active {
  background: var(--nav-active);
}

.mode[aria-checked='true'] {
  border-color: var(--ink);
  background: var(--nav-active);
}

.mode-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
}

.mode-title {
  font-size: 18px;
  font-weight: 600;
  line-height: 28px;
}

.mode-meta,
.mode-night,
.copy {
  color: var(--muted);
  font-size: 14px;
  line-height: 20px;
}

.mode-roster {
  font-size: 16px;
  line-height: 24px;
}

.advanced,
.close,
.button,
.choice {
  border-radius: 8px;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease, opacity 160ms ease;
}

.advanced {
  align-self: flex-start;
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid var(--line);
  background: transparent;
  color: inherit;
}

.advanced[aria-expanded='true'] {
  border-color: var(--ink);
  background: var(--nav-active);
}

.close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border: 0;
  background: transparent;
  color: inherit;
}

.close svg {
  width: 16px;
  height: 16px;
}

.advanced:hover,
.close:hover,
.button:hover:not(:disabled),
.choice:hover:not([aria-checked='true']) {
  background: var(--nav-hover);
}

.mode:focus-visible,
.advanced:focus-visible,
.close:focus-visible,
.button:focus-visible,
.choice:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.choice:active:not(:disabled),
.button:active:not(:disabled),
.advanced:active,
.close:active {
  background: var(--nav-active);
}

.options {
  display: flex;
  flex-direction: column;
  gap: 24px;
  animation: options-in 280ms ease both;
}

.option {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 0;
  border-top: 1px solid var(--line);
}

.option-title {
  font-size: 16px;
  font-weight: 600;
  line-height: 24px;
}

.choices {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.choice {
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid var(--line);
  background: transparent;
  color: inherit;
}

.choice[aria-checked='true'] {
  border-color: var(--action);
  background: var(--action);
  color: var(--action-text);
}

.choice[aria-checked='true']:hover {
  border-color: var(--action-hover);
  background: var(--action-hover);
}

.button {
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid var(--line);
  background: transparent;
  color: inherit;
}

.button.primary {
  border-color: var(--action);
  background: var(--action);
  color: var(--action-text);
}

.button.primary:hover:not(:disabled) {
  border-color: var(--action-hover);
  background: var(--action-hover);
}

.button.primary:active:not(:disabled) {
  border-color: var(--action-press);
  background: var(--action-press);
}

.button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.notice {
  color: var(--danger);
  font-size: 14px;
  line-height: 20px;
}

@keyframes setup-backdrop-in {
  0% {
    background-color: transparent;
  }

  32% {
    background-color: rgba(0, 0, 0, 0.48);
  }

  100% {
    background-color: rgba(0, 0, 0, 0.48);
  }
}

@keyframes setup-backdrop-out {
  from {
    background-color: rgba(0, 0, 0, 0.48);
  }

  to {
    background-color: transparent;
  }
}

@keyframes setup-dialog-in {
  0% {
    opacity: 0;
    transform: translateY(16px) scale(0.94);
  }

  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes setup-dialog-out {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }

  to {
    opacity: 0;
    transform: translateY(8px) scale(0.96);
  }
}

@keyframes options-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 640px) {
  .head,
  .foot,
  .body {
    padding-right: 16px;
    padding-left: 16px;
  }

  .mode-top {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .backdrop,
  .backdrop.setup-enter-active,
  .backdrop.setup-leave-active,
  .dialog,
  .dialog.is-sized,
  .setup-enter-active .dialog,
  .setup-leave-active .dialog,
  .options,
  .mode,
  .advanced,
  .close,
  .button,
  .choice {
    animation: none;
    transition: none;
  }
}
</style>
