<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { ApiError, fetchModules, type GameModule } from '../api'
import GameModuleCard from './GameModuleCard.vue'
import GameSetupDialog from './GameSetupDialog.vue'
import GameTable from './GameTable.vue'
import ChessTable from './ChessTable.vue'

const props = defineProps<{
  playing: boolean
}>()

const emit = defineEmits<{
  enter: []
  leave: []
}>()

const modules = ref<GameModule[]>([])
const loaded = ref(false)
const error = ref('')
const activeId = ref('')
const activeName = ref('')
const setupOpen = ref(false)
const atTable = ref(false)
const card = ref<{ focus: () => void } | null>(null)
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

function registerCard(element: unknown): void {
  if (element && typeof element === 'object' && 'focus' in element && typeof element.focus === 'function') {
    card.value = element as { focus: () => void }
    return
  }
  card.value = null
}

function openGame(game: GameModule): void {
  activeId.value = game.id
  activeName.value = game.name
  atTable.value = false
  setupOpen.value = true
  emit('enter')
}

function beginTable(): void {
  setupOpen.value = false
  atTable.value = true
}

watch(
  () => props.playing,
  (value, previous) => {
    if (previous && !value) {
      atTable.value = false
      setupOpen.value = false
      void nextTick(() => card.value?.focus())
    }
  },
)

onMounted(() => {
  void fetchModules()
    .then((items) => {
      modules.value = items
    })
    .catch((caught: unknown) => {
      error.value = caught instanceof ApiError ? caught.message : '无法读取游戏模块。'
    })
    .finally(() => {
      loaded.value = true
    })
})
</script>

<template>
  <div class="presence">
    <Transition :css="!reduceMotion" name="presence">
      <section v-if="playing" key="game" class="game" :aria-label="activeName">
        <Transition
          :css="!reduceMotion"
          name="setup"
          :duration="reduceMotion ? { enter: 1, leave: 1 } : { enter: 520, leave: 240 }"
        >
          <GameSetupDialog
            v-if="setupOpen && activeId"
            :module-id="activeId"
            @leave="emit('leave')"
            @start="beginTable"
          />
        </Transition>
        <GameTable v-if="atTable && activeId === 'werewolf' && !setupOpen" :module-id="activeId" />
        <ChessTable v-if="atTable && activeId === 'xiangqi' && !setupOpen" :module-id="activeId" />
      </section>
      <section v-else key="lobby" class="modules" aria-label="游戏">
        <p v-if="error" class="modules-note" role="alert">{{ error }}</p>
        <p v-else-if="loaded && modules.length === 0" class="modules-note">还没有游戏模块。</p>
        <GameModuleCard
          v-for="game in modules"
          :key="game.id"
          :ref="(element) => registerCard(element)"
          :game="game"
          @done="openGame(game)"
        />
      </section>
    </Transition>
  </div>
</template>

<style scoped>
.presence {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}

.presence-enter-active,
.presence-leave-active {
  transition: opacity 480ms ease;
}

.presence-enter-from,
.presence-leave-to {
  opacity: 0;
}

.presence-leave-active {
  position: absolute;
  inset: 0;
  z-index: 1;
}

.modules {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 360px));
  gap: 16px;
  align-content: start;
  flex: 1;
  min-height: 0;
  padding: 24px;
  overflow: auto;
}

.game {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  background: #14110e;
}

.modules-note {
  margin: 0;
  color: var(--muted);
}

@media (max-width: 640px) {
  .modules {
    grid-template-columns: minmax(0, 1fr);
    padding: 16px;
  }
}
</style>
