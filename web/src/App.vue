<script setup lang="ts">
import { nextTick, ref } from 'vue'
import logoUrl from './assets/logo.png'
import GameModules from './components/GameModules.vue'
import SettingsDialog from './components/SettingsDialog.vue'

const open = ref(false)
const covered = ref(false)
const playing = ref(false)
const settingsButton = ref<HTMLButtonElement | null>(null)
const backButton = ref<HTMLButtonElement | null>(null)
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

function onEnterGame(): void {
  playing.value = true
  void nextTick(() => backButton.value?.focus())
}

function leaveGame(): void {
  playing.value = false
}

function openSettings(): void {
  covered.value = true
  open.value = true
}

function closeSettings(): void {
  open.value = false
}

function onBeforeLeave(element: Element): void {
  if (element instanceof HTMLElement) {
    element.setAttribute('inert', '')
  }
}

function onAfterLeave(): void {
  covered.value = false
  void nextTick(() => settingsButton.value?.focus())
}
</script>

<template>
  <div class="shell" :inert="covered">
    <header class="topbar" :class="{ 'is-playing': playing }">
      <div class="lead">
        <div class="back-slot">
          <button
            ref="backButton"
            class="back"
            type="button"
            aria-label="返回"
            :inert="!playing"
            @click="leaveGame"
          >
            <span class="back-mark" aria-hidden="true">&lt;</span>
          </button>
        </div>
        <div class="brand">
          <img class="logo" :src="logoUrl" alt="" width="1346" height="589" />
          <span class="wordmark">AgentArena</span>
        </div>
      </div>
      <button
        ref="settingsButton"
        class="settings"
        type="button"
        aria-haspopup="dialog"
        :aria-expanded="open"
        @click="openSettings"
      >
        <svg class="settings-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path
            fill="currentColor"
            d="M19.14 12.94a7.4 7.4 0 0 0 .06-.94c0-.32-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.2 7.2 0 0 0-1.63-.94l-.36-2.54a.5.5 0 0 0-.49-.42h-3.84a.5.5 0 0 0-.49.42l-.36 2.54c-.58.23-1.12.54-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.71 8.84a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.62-.06.94s.02.63.06.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.13.22.4.32.64.22l2.39-.96c.5.4 1.05.71 1.63.94l.36 2.54c.05.24.26.42.49.42h3.84c.24 0 .44-.18.49-.42l.36-2.54c.58-.23 1.13-.54 1.63-.94l2.39.96c.24.1.51 0 .64-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z"
          />
        </svg>
        设置
      </button>
    </header>
    <main class="stage">
      <GameModules :playing="playing" @enter="onEnterGame" @leave="leaveGame" />
    </main>
  </div>
  <Transition
    name="settings"
    :duration="reduceMotion ? { enter: 1, leave: 1 } : { enter: 520, leave: 240 }"
    @before-leave="onBeforeLeave"
    @after-leave="onAfterLeave"
  >
    <SettingsDialog v-if="open" @close="closeSettings" />
  </Transition>
</template>
