<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { fetchQiniuModelCount, type Theme } from '../api'
import { loadSettings, removeQiniuApiKey, saveQiniuApiKey, saveTheme, settings } from '../settings'

const emit = defineEmits<{ close: [] }>()

const dialog = ref<HTMLElement | null>(null)
const body = ref<HTMLElement | null>(null)
const themesEl = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
const thumbReady = ref(false)
const thumbX = ref(0)
const thumbW = ref(0)
let sizeObserver: ResizeObserver | null = null
let themeObserver: ResizeObserver | null = null
let sizeReady = false
let lastWidth = -1
let lastHeight = -1
const section = ref<'general' | 'api'>('general')
const apiKey = ref('')
const revealed = ref(false)
const confirmClear = ref(false)
const savingTheme = ref(false)
const savingKey = ref(false)
const testing = ref(false)
const themeError = ref<string | null>(null)
const keyNotice = ref<{ tone: 'ok' | 'error'; text: string } | null>(null)

const themes: { id: Theme; label: string }[] = [
  { id: 'system', label: '跟随系统' },
  { id: 'light', label: '浅色' },
  { id: 'dark', label: '深色' },
]

const sectionTitle = computed(() => (section.value === 'general' ? '通用' : 'API 密钥'))
const unsavedKey = computed(() => apiKey.value.trim().length > 0)
const saveDisabled = computed(() => savingKey.value || !unsavedKey.value)
const testDisabled = computed(
  () => testing.value || savingKey.value || !settings.qiniuConfigured || unsavedKey.value,
)

onMounted(async () => {
  document.body.style.overflow = 'hidden'
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onResize)
  bindSize()
  await nextTick()
  closeButton.value?.focus()
  placeThumb(false)
  bindThemeObserver()
  await loadSettings()
})

onUnmounted(() => {
  document.body.style.overflow = ''
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onResize)
  sizeObserver?.disconnect()
  themeObserver?.disconnect()
})

watch(section, (value) => {
  if (value !== 'general') {
    themeObserver?.disconnect()
    return
  }
  void nextTick(() => {
    placeThumb(false)
    bindThemeObserver()
  })
})

watch(
  () => settings.theme,
  () => placeThumb(true),
)

function measureBox(): { width: number; height: number } | null {
  const shell = dialog.value
  const inner = body.value
  if (!shell || !inner) {
    return null
  }
  const parent = shell.parentElement
  const parentStyles = parent ? getComputedStyle(parent) : null
  const padX = parentStyles ? parseFloat(parentStyles.paddingLeft) + parseFloat(parentStyles.paddingRight) : 32
  const padY = parentStyles ? parseFloat(parentStyles.paddingTop) + parseFloat(parentStyles.paddingBottom) : 32
  const availableWidth = (parent?.clientWidth ?? window.innerWidth) - padX
  const availableHeight = (parent?.clientHeight ?? window.innerHeight) - padY
  const shellStyles = getComputedStyle(shell)
  const borderY = parseFloat(shellStyles.borderTopWidth) + parseFloat(shellStyles.borderBottomWidth)
  return {
    width: Math.round(Math.min(560, availableWidth)),
    height: Math.round(Math.min(availableHeight, inner.offsetHeight + borderY)),
  }
}

function writeSize(animate: boolean): void {
  const shell = dialog.value
  const next = measureBox()
  if (!shell || !next || (next.width === lastWidth && next.height === lastHeight)) {
    return
  }
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const previousWidth = shell.offsetWidth
  const previousHeight = shell.offsetHeight
  lastWidth = next.width
  lastHeight = next.height
  if (!animate || reduce || !sizeReady) {
    shell.classList.remove('is-sized')
    shell.style.width = `${next.width}px`
    shell.style.height = `${next.height}px`
    if (sizeReady && !reduce) {
      requestAnimationFrame(() => {
        dialog.value?.classList.add('is-sized')
      })
    }
    return
  }
  shell.classList.remove('is-sized')
  shell.style.width = `${previousWidth}px`
  shell.style.height = `${previousHeight}px`
  void shell.offsetHeight
  shell.classList.add('is-sized')
  shell.style.width = `${next.width}px`
  shell.style.height = `${next.height}px`
}

function bindSize(): void {
  writeSize(false)
  const inner = body.value
  if (!inner) {
    return
  }
  requestAnimationFrame(() => {
    dialog.value?.classList.add('is-sized')
    sizeReady = true
  })
  sizeObserver = new ResizeObserver(() => {
    writeSize(true)
  })
  sizeObserver.observe(inner)
}

function onResize(): void {
  writeSize(true)
}

function placeThumb(animate: boolean): void {
  const root = themesEl.value
  if (!root) {
    return
  }
  const current = root.querySelector<HTMLElement>(`[data-theme-option="${settings.theme}"]`)
  if (!current) {
    return
  }
  if (!animate) {
    thumbReady.value = false
  }
  thumbX.value = current.offsetLeft
  thumbW.value = current.offsetWidth
  if (!animate) {
    requestAnimationFrame(() => {
      thumbReady.value = true
    })
  }
}

function bindThemeObserver(): void {
  themeObserver?.disconnect()
  const root = themesEl.value
  if (!root) {
    return
  }
  themeObserver = new ResizeObserver(() => {
    const current = root.querySelector<HTMLElement>(`[data-theme-option="${settings.theme}"]`)
    if (!current) {
      return
    }
    thumbX.value = current.offsetLeft
    thumbW.value = current.offsetWidth
  })
  themeObserver.observe(root)
}

function onSectionKeydown(event: KeyboardEvent): void {
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') {
    return
  }
  event.preventDefault()
  section.value = section.value === 'general' ? 'api' : 'general'
  void nextTick(() => {
    dialog.value?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus()
  })
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !dialog.value) {
    return
  }
  const focusable = [...dialog.value.querySelectorAll<HTMLElement>('button, a[href], input')].filter(
    (element) => !element.hasAttribute('disabled') && element.tabIndex !== -1,
  )
  if (focusable.length === 0) {
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (!first || !last) {
    return
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

async function chooseTheme(theme: Theme): Promise<void> {
  if (savingTheme.value || settings.theme === theme) {
    return
  }
  savingTheme.value = true
  themeError.value = null
  try {
    await saveTheme(theme)
  } catch (error) {
    themeError.value = error instanceof Error ? error.message : '主题没有保存。'
  } finally {
    savingTheme.value = false
  }
  await nextTick()
  dialog.value?.querySelector<HTMLElement>(`[data-theme-option="${settings.theme}"]`)?.focus()
}

function onThemeKeydown(event: KeyboardEvent, theme: Theme): void {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft' && event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
    return
  }
  event.preventDefault()
  const index = themes.findIndex((item) => item.id === theme)
  const delta = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1
  const next = themes[(index + delta + themes.length) % themes.length]
  if (next) {
    void chooseTheme(next.id)
  }
}

function onKeyInput(): void {
  confirmClear.value = false
  keyNotice.value = null
}

async function saveKey(): Promise<void> {
  const value = apiKey.value.trim()
  if (!value || savingKey.value) {
    return
  }
  savingKey.value = true
  keyNotice.value = null
  try {
    await saveQiniuApiKey(value)
    apiKey.value = ''
    revealed.value = false
    confirmClear.value = false
    keyNotice.value = { tone: 'ok', text: '已保存。' }
  } catch (error) {
    keyNotice.value = { tone: 'error', text: error instanceof Error ? error.message : '密钥没有保存。' }
  } finally {
    savingKey.value = false
  }
}

async function testKey(): Promise<void> {
  if (testDisabled.value) {
    return
  }
  testing.value = true
  keyNotice.value = null
  try {
    const count = await fetchQiniuModelCount()
    keyNotice.value = { tone: 'ok', text: `已连通，可用模型 ${count} 个。` }
  } catch (error) {
    keyNotice.value = { tone: 'error', text: error instanceof Error ? error.message : '连接失败。' }
  } finally {
    testing.value = false
  }
}

async function clearKey(): Promise<void> {
  if (!settings.qiniuConfigured || savingKey.value) {
    return
  }
  if (!confirmClear.value) {
    confirmClear.value = true
    return
  }
  savingKey.value = true
  keyNotice.value = null
  try {
    await removeQiniuApiKey()
    confirmClear.value = false
    keyNotice.value = { tone: 'ok', text: '已清除。' }
  } catch (error) {
    keyNotice.value = { tone: 'error', text: error instanceof Error ? error.message : '密钥没有清除。' }
  } finally {
    savingKey.value = false
  }
}
</script>

<template>
  <div class="backdrop" @mousedown.self="emit('close')">
    <div
      ref="dialog"
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
    >
      <div class="dialog-fill" aria-hidden="true">
        <div class="dialog-fill-nav"></div>
      </div>
      <div ref="body" class="dialog-body">
      <div class="nav" role="tablist" aria-label="设置分类" @keydown="onSectionKeydown">
        <button
          class="nav-item"
          type="button"
          role="tab"
          :aria-selected="section === 'general'"
          :tabindex="section === 'general' ? 0 : -1"
          @click="section = 'general'"
        >
          通用
        </button>
        <button
          class="nav-item"
          type="button"
          role="tab"
          :aria-selected="section === 'api'"
          :tabindex="section === 'api' ? 0 : -1"
          @click="section = 'api'"
        >
          API 密钥
        </button>
      </div>
      <div class="content">
        <div class="content-head">
          <h2 id="settings-title">
            <Transition name="title">
              <span :key="section" class="title-text">{{ sectionTitle }}</span>
            </Transition>
          </h2>
          <button ref="closeButton" class="close" type="button" aria-label="关闭设置" @click="emit('close')">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M6.7 5.3a1 1 0 0 0-1.4 1.4L10.58 12l-5.3 5.3a1 1 0 1 0 1.42 1.4L12 13.42l5.3 5.3a1 1 0 0 0 1.4-1.42L13.42 12l5.3-5.3a1 1 0 0 0-1.42-1.4L12 10.58l-5.3-5.28z"
              />
            </svg>
          </button>
        </div>

        <Transition name="reveal">
          <p v-if="settings.loadError" class="notice error" role="alert">{{ settings.loadError }}</p>
        </Transition>

        <div class="pane-slot">
        <Transition name="pane">
        <section v-if="section === 'general'" key="general" class="pane" role="tabpanel" aria-labelledby="theme-label">
          <h3 id="theme-label">主题</h3>
          <p class="copy">选择浅色、深色，或跟随系统。</p>
          <div
            ref="themesEl"
            class="themes"
            :class="{ 'thumb-ready': thumbReady }"
            role="radiogroup"
            aria-labelledby="theme-label"
          >
            <span
              class="theme-thumb"
              aria-hidden="true"
              :style="{ width: `${thumbW}px`, transform: `translateX(${thumbX}px)` }"
            />
            <button
              v-for="item in themes"
              :key="item.id"
              class="theme-option"
              type="button"
              role="radio"
              :data-theme-option="item.id"
              :aria-checked="settings.theme === item.id"
              :disabled="savingTheme"
              @click="chooseTheme(item.id)"
              @keydown="onThemeKeydown($event, item.id)"
            >
              <svg v-if="item.id === 'system'" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v9A2.5 2.5 0 0 1 17.5 17H13v2h2a1 1 0 1 1 0 2H9a1 1 0 1 1 0-2h2v-2H6.5A2.5 2.5 0 0 1 4 14.5v-9zM6.5 5a.5.5 0 0 0-.5.5v9c0 .28.22.5.5.5h11a.5.5 0 0 0 .5-.5v-9a.5.5 0 0 0-.5-.5h-11z"
                />
              </svg>
              <svg v-else-if="item.id === 'light'" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M12 6.2a5.8 5.8 0 1 0 0 11.6 5.8 5.8 0 0 0 0-11.6zM12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM11 1h2v3h-2V1zm0 19h2v3h-2v-3zM1 11h3v2H1v-2zm19 0h3v2h-3v-2zM4.2 5.05l1.42-1.41 2.12 2.12-1.41 1.42-2.13-2.13zM16.26 17.1l1.41-1.41 2.12 2.12-1.41 1.41-2.12-2.12zM18.38 3.64l1.42 1.41-2.13 2.13-1.41-1.42 2.12-2.12zM6.32 15.7l1.41 1.41-2.12 2.12-1.41-1.41 2.12-2.12z"
                />
              </svg>
              <svg v-else viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M14.2 2.4a1 1 0 0 1 .35 1.3A7.2 7.2 0 0 0 20.4 14a7.2 7.2 0 0 1-9.1 6.85 1 1 0 0 1 .2-1.94 5.2 5.2 0 0 0 4.7-8.1 1 1 0 0 1 1.1-1.5A9.2 9.2 0 0 0 14.2 2.4z"
                />
              </svg>
              {{ item.label }}
            </button>
          </div>
          <Transition name="reveal">
            <p v-if="themeError" class="notice error" role="alert">{{ themeError }}</p>
          </Transition>
        </section>

        <section v-else key="api" class="pane" role="tabpanel" aria-labelledby="settings-title">
          <p class="copy">
            密钥只保存在服务端。说明见
            <a
              href="https://developer-doc.qiniu.com/products/aitokenapi/inference-api/1-real-time-ai-interface-api"
              target="_blank"
              rel="noopener noreferrer"
              >实时推理</a
            >
            和
            <a
              href="https://developer-doc.qiniu.com/products/aitokenapi/inference-api/0-chat-completions"
              target="_blank"
              rel="noopener noreferrer"
              >聊天补全</a
            >。
          </p>
          <p v-if="settings.qiniuConfigured" class="status">
            已保存<template v-if="settings.qiniuHint">，末四位 {{ settings.qiniuHint }}</template>。
          </p>
          <p v-else class="status">尚未保存密钥。</p>
          <form @submit.prevent="saveKey">
            <label class="field-label" for="qiniu-api-key">七牛云 API 密钥</label>
            <div class="field-row">
              <input
                id="qiniu-api-key"
                v-model="apiKey"
                class="field"
                :type="revealed ? 'text' : 'password'"
                name="qiniu-api-key"
                autocomplete="off"
                spellcheck="false"
                maxlength="2048"
                placeholder="输入新的密钥"
                @input="onKeyInput"
              />
              <button class="button" type="button" @click="revealed = !revealed">
                {{ revealed ? '隐藏' : '显示' }}
              </button>
            </div>
            <Transition name="reveal">
              <p v-if="unsavedKey" class="copy">输入框里的密钥还没有保存。测试连接使用的是已保存的密钥。</p>
            </Transition>
            <div class="actions">
              <button class="button primary" type="submit" :disabled="saveDisabled">
                {{ savingKey ? '保存中' : '保存' }}
              </button>
              <button class="button" type="button" :disabled="testDisabled" @click="testKey">
                {{ testing ? '测试中' : '测试连接' }}
              </button>
              <button
                class="button danger"
                type="button"
                :disabled="!settings.qiniuConfigured || savingKey"
                @click="clearKey"
              >
                {{ confirmClear ? '确认清除' : '清除' }}
              </button>
            </div>
          </form>
          <Transition name="reveal">
            <p
              v-if="keyNotice"
              class="notice"
              :class="keyNotice.tone"
              :role="keyNotice.tone === 'error' ? 'alert' : 'status'"
            >
              {{ keyNotice.text }}
            </p>
          </Transition>
        </section>
        </Transition>
        </div>
      </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.48);
}

.dialog {
  position: relative;
  display: block;
  width: min(560px, 100%);
  min-width: 0;
  min-height: 0;
  max-height: calc(100dvh - 32px);
  overflow: hidden;
  transform-origin: center center;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel);
  color: var(--ink);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.24);
}

.dialog.is-sized {
  transition:
    width 480ms cubic-bezier(0.22, 1.28, 0.36, 1),
    height 480ms cubic-bezier(0.22, 1.28, 0.36, 1);
}

.dialog-fill {
  position: absolute;
  inset: 0;
  display: flex;
  pointer-events: none;
  background: var(--panel);
}

.dialog-fill-nav {
  width: 160px;
  flex: none;
  background: var(--panel-muted);
  border-right: 1px solid var(--line);
}

.dialog-body {
  position: relative;
  z-index: 1;
  display: flex;
  width: 100%;
}

.settings-enter-active {
  animation: settings-backdrop-in 520ms linear both;
}

.settings-leave-active {
  animation: settings-backdrop-out 240ms ease both;
}

.settings-enter-active .dialog {
  animation: dialog-in 520ms cubic-bezier(0.22, 1.28, 0.36, 1) both;
}

.settings-leave-active .dialog {
  animation: dialog-out 240ms cubic-bezier(0.4, 0, 1, 1) both;
}

@keyframes settings-backdrop-in {
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

@keyframes settings-backdrop-out {
  from {
    background-color: rgba(0, 0, 0, 0.48);
  }

  to {
    background-color: transparent;
  }
}

@keyframes dialog-in {
  0% {
    opacity: 0;
    transform: translateY(16px) scale(0.94);
  }

  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes dialog-out {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }

  to {
    opacity: 0;
    transform: translateY(8px) scale(0.96);
  }
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 160px;
  flex: 0 0 160px;
  padding: 16px;
  background: var(--panel-muted);
  border-right: 1px solid var(--line);
}

.nav-item {
  min-height: 44px;
  padding: 8px 16px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition: background-color 160ms ease;
}

.nav-item:hover {
  background: var(--nav-hover);
}

.nav-item:active {
  background: var(--nav-active);
}

.nav-item[aria-selected='true'] {
  background: var(--nav-active);
}

.theme-option:hover:not(:disabled):not([aria-checked='true']) {
  background: var(--nav-hover);
}

.nav-item:focus-visible,
.theme-option:focus-visible,
.button:focus-visible,
.field:focus-visible,
.close:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.content {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  flex: 1;
  padding: 16px 24px 24px;
  overflow: hidden;
}

.content-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 44px;
}

h2,
h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  line-height: 28px;
}

h2 {
  position: relative;
  min-height: 28px;
}

.title-text {
  display: inline-block;
}

.title-enter-active,
.title-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.title-enter-from,
.title-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

.title-leave-active {
  position: absolute;
  left: 0;
  top: 0;
}

h3 {
  font-size: 16px;
  line-height: 24px;
}

.close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  transition: background-color 160ms ease;
}

.close svg,
.theme-option svg {
  width: 16px;
  height: 16px;
}

.close:hover,
.button:hover:not(:disabled) {
  background: var(--nav-hover);
}

.close:active,
.button:active:not(:disabled),
.theme-option:active:not(:disabled) {
  background: var(--nav-active);
}

.pane-slot,
.pane,
form {
  position: relative;
}

.pane-slot {
  overflow: hidden;
}

.pane {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pane-enter-active,
.pane-leave-active {
  transition: opacity 200ms ease, transform 280ms cubic-bezier(0.22, 1.15, 0.36, 1);
}

.pane-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.pane-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.pane-leave-active {
  position: absolute;
  z-index: 1;
  top: 0;
  right: 0;
  left: 0;
  pointer-events: none;
}

.reveal-enter-active,
.reveal-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.reveal-enter-from,
.reveal-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.reveal-leave-active {
  position: absolute;
  left: 0;
  right: 0;
}

.copy,
.status {
  margin: 0;
  color: var(--muted);
  font-size: 14px;
  line-height: 20px;
}

.copy a {
  color: var(--ink);
}

.themes {
  position: relative;
  display: flex;
  width: fit-content;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid var(--field-border);
  border-radius: 8px;
}

.theme-thumb {
  position: absolute;
  z-index: 0;
  top: 0;
  bottom: 0;
  left: 0;
  width: 0;
  background: var(--action);
  pointer-events: none;
}

.themes.thumb-ready .theme-thumb {
  transition:
    transform 420ms cubic-bezier(0.22, 1.28, 0.36, 1),
    width 420ms cubic-bezier(0.22, 1.28, 0.36, 1);
}

.theme-option {
  position: relative;
  z-index: 1;
  display: inline-flex;
  flex: 0 1 auto;
  flex-direction: row;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 0;
  min-height: 44px;
  padding: 8px 16px;
  border: 0;
  border-right: 1px solid var(--field-border);
  border-radius: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  cursor: pointer;
  transition: background-color 160ms ease, opacity 160ms ease;
}

.theme-option:last-child {
  border-right: 0;
}

.theme-option[aria-checked='true'] {
  background: var(--action);
  color: var(--action-text);
}

.themes.thumb-ready .theme-option[aria-checked='true'] {
  background: transparent;
}

.theme-option:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
}

.field-row {
  display: flex;
  gap: 8px;
}

.field {
  min-width: 0;
  flex: 1;
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid var(--field-border);
  border-radius: 8px;
  background: var(--field);
  color: inherit;
  font: inherit;
  transition: background-color 160ms ease, border-color 160ms ease;
}

.field:hover {
  border-color: var(--ink);
}

.field::placeholder {
  color: var(--muted);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.button {
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease, opacity 160ms ease;
}

.button.primary {
  border-color: var(--action);
  background: var(--action);
  color: var(--action-text);
}

.button.primary:hover:not(:disabled) {
  border-color: var(--action-hover);
  background: var(--action-hover);
  color: var(--action-text);
}

.button.primary:active:not(:disabled) {
  border-color: var(--action-press);
  background: var(--action-press);
  color: var(--action-text);
}

.button.danger {
  color: var(--danger);
}

.button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.notice {
  margin: 0;
  font-size: 14px;
  line-height: 20px;
}

.notice.ok {
  color: var(--ok);
}

.notice.error {
  color: var(--danger);
}

@media (max-width: 640px) {
  .dialog-fill-nav {
    display: none;
  }

  .dialog-body {
    flex-direction: column;
  }

  .nav {
    flex-direction: row;
    width: auto;
    flex-basis: auto;
    padding: 16px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .nav-item {
    flex: 1;
    text-align: center;
  }

  .content {
    padding: 16px;
  }

  .themes {
    width: 100%;
  }

  .theme-option {
    flex: 1 1 0;
    padding: 8px 12px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .dialog,
  .dialog.is-sized,
  .settings-enter-active,
  .settings-leave-active,
  .settings-enter-active .dialog,
  .settings-leave-active .dialog,
  .pane-enter-active,
  .pane-leave-active,
  .title-enter-active,
  .title-leave-active,
  .reveal-enter-active,
  .reveal-leave-active,
  .themes.thumb-ready .theme-thumb,
  .theme-option,
  .nav-item,
  .button,
  .close,
  .field {
    animation: none;
    transition: none;
  }
}
</style>
