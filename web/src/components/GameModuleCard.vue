<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { GameModule } from '../api'

const props = defineProps<{
  game: GameModule
}>()

const emit = defineEmits<{
  done: []
}>()

const particleCount = 16
const strokeWidth = 2.5
const particleLength = 44
const frame = ref<HTMLElement | null>(null)
const buttonEl = ref<HTMLButtonElement | null>(null)
const orbitSvg = ref<SVGSVGElement | null>(null)
const flight = ref<Flight | null>(null)
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const particleEls: SVGPathElement[] = []

let raf = 0
let last = 0
let travel = 0
let velocity = 1 / 9600
let finished = false
let flightTimer = 0

interface Flight {
  top: number
  left: number
  width: number
  height: number
  open: boolean
}

function particleOpacity(index: number): number {
  const turns = index / particleCount
  const distance = Math.min(turns, 1 - turns)
  const edge = 0.4
  if (distance >= edge) {
    return 0
  }
  return (1 - distance / edge) ** 1.15
}

function setParticle(index: number, element: unknown): void {
  if (element instanceof SVGPathElement) {
    particleEls[index] = element
  }
}

function roundedRectPath(width: number, height: number, radius: number): string {
  const inset = strokeWidth / 2
  const x = inset
  const y = inset
  const w = Math.max(0, width - inset * 2)
  const h = Math.max(0, height - inset * 2)
  const r = Math.max(0, Math.min(radius - inset, w / 2, h / 2))
  const right = x + w
  const bottom = y + h
  if (r === 0) {
    return `M ${x} ${y} H ${right} V ${bottom} H ${x} V ${y} Z`
  }
  return [
    `M ${x + r} ${y}`,
    `H ${right - r}`,
    `A ${r} ${r} 0 0 1 ${right} ${y + r}`,
    `V ${bottom - r}`,
    `A ${r} ${r} 0 0 1 ${right - r} ${bottom}`,
    `H ${x + r}`,
    `A ${r} ${r} 0 0 1 ${x} ${bottom - r}`,
    `V ${y + r}`,
    `A ${r} ${r} 0 0 1 ${x + r} ${y}`,
    'Z',
  ].join(' ')
}

function placeParticles(now: number): void {
  if (!last) {
    last = now
  }
  const dt = Math.min(32, now - last)
  last = now
  const target = flight.value?.open ? 1 / 4200 : 1 / 9600
  velocity += (target - velocity) * Math.min(1, dt / 220)
  travel = (travel + velocity * dt) % 1

  const svg = orbitSvg.value
  const frameEl = frame.value
  if (!svg || !frameEl) {
    return
  }
  const box = svg.getBoundingClientRect()
  if (box.width < 1 || box.height < 1) {
    return
  }
  const button = frameEl.querySelector('.module')
  const radius = button instanceof HTMLElement ? parseFloat(getComputedStyle(button).borderTopLeftRadius) || 0 : 16
  const d = roundedRectPath(box.width, box.height, radius)
  const viewBox = `0 0 ${box.width} ${box.height}`
  if (svg.getAttribute('viewBox') !== viewBox) {
    svg.setAttribute('viewBox', viewBox)
  }
  let length = 0
  for (let index = 0; index < particleEls.length; index += 1) {
    const el = particleEls[index]
    if (!el) {
      continue
    }
    if (el.getAttribute('d') !== d) {
      el.setAttribute('d', d)
    }
    if (length === 0) {
      length = el.getTotalLength()
    }
    if (length === 0) {
      return
    }
    const dash = Math.min(particleLength, length * 0.45)
    const gap = Math.max(length - dash, 0.01)
    const along = (travel + index / particleCount) % 1
    const start = along * length - dash / 2
    el.setAttribute('stroke-dasharray', `${dash} ${gap}`)
    el.setAttribute('stroke-dashoffset', `${-start}`)
  }
}

function tick(now: number): void {
  raf = requestAnimationFrame(tick)
  placeParticles(now)
}

function startLoop(): void {
  if (raf || reduceMotion) {
    return
  }
  last = 0
  raf = requestAnimationFrame(tick)
}

function stopLoop(): void {
  if (raf) {
    cancelAnimationFrame(raf)
  }
  raf = 0
}

function finish(): void {
  if (finished) {
    return
  }
  finished = true
  window.clearTimeout(flightTimer)
  stopLoop()
  emit('done')
}

function destination(current: DOMRect): Flight {
  const stage = frame.value?.closest('.stage')
  if (!(stage instanceof HTMLElement)) {
    return { top: current.top, left: current.left, width: current.width, height: current.height, open: true }
  }
  const rect = stage.getBoundingClientRect()
  const header = parseFloat(getComputedStyle(stage).paddingTop) || 0
  return {
    top: rect.top + header,
    left: rect.left,
    width: rect.width,
    height: Math.max(0, rect.height - header),
    open: true,
  }
}

function enterGame(): void {
  if (flight.value || finished) {
    return
  }
  if (reduceMotion || !frame.value) {
    finish()
    return
  }
  const rect = frame.value.getBoundingClientRect()
  flight.value = {
    top: rect.top,
    left: rect.left,
    width: rect.width,
    height: rect.height,
    open: false,
  }
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      if (!frame.value || finished) {
        return
      }
      flight.value = destination(rect)
      flightTimer = window.setTimeout(finish, 980)
    })
  })
}

function onFlightEnd(event: TransitionEvent): void {
  if (event.target !== frame.value || !flight.value?.open) {
    return
  }
  if (event.propertyName !== 'width' && event.propertyName !== 'height') {
    return
  }
  finish()
}

onMounted(() => {
  startLoop()
})

function focus(): void {
  buttonEl.value?.focus()
}

defineExpose({ focus })

onBeforeUnmount(() => {
  window.clearTimeout(flightTimer)
  stopLoop()
})
</script>

<template>
  <div
    ref="frame"
    class="module-frame"
    :class="{ 'is-flight': flight !== null, 'is-open': flight?.open }"
    :style="
      flight
        ? {
            top: `${flight.top}px`,
            left: `${flight.left}px`,
            width: `${flight.width}px`,
            height: `${flight.height}px`,
          }
        : undefined
    "
    @transitionend="onFlightEnd"
  >
    <button
      ref="buttonEl"
      class="module"
      type="button"
      :aria-labelledby="`${game.id}-name`"
      :aria-describedby="`${game.id}-description`"
      :aria-busy="flight !== null"
      @click="enterGame"
    >
      <img class="module-cover" :src="props.game.coverUrl" alt="" width="1440" height="1440" draggable="false" />
      <span class="module-copy">
        <span :id="`${game.id}-name`" class="module-name">{{ props.game.name }}</span>
        <span :id="`${game.id}-description`" class="module-description">{{ props.game.description }}</span>
      </span>
    </button>
    <span v-if="!reduceMotion" class="orbit" aria-hidden="true">
      <svg ref="orbitSvg" class="orbit-geom">
        <path
          v-for="index in particleCount"
          :key="index"
          :ref="(el) => setParticle(index - 1, el)"
          class="particle"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          :style="{ opacity: particleOpacity(index - 1) }"
        />
      </svg>
    </span>
  </div>
</template>

<style scoped>
.module-frame {
  position: relative;
  aspect-ratio: 1 / 1;
  min-width: 0;
}

.module-frame.is-flight {
  position: fixed;
  z-index: 10;
  aspect-ratio: auto;
  margin: 0;
  pointer-events: none;
}

.module-frame.is-open {
  transition:
    top 800ms cubic-bezier(0.22, 1, 0.36, 1),
    left 800ms cubic-bezier(0.22, 1, 0.36, 1),
    width 800ms cubic-bezier(0.22, 1, 0.36, 1),
    height 800ms cubic-bezier(0.22, 1, 0.36, 1);
}

.module {
  position: relative;
  display: block;
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  touch-action: manipulation;
  user-select: none;
  transition:
    border-color 160ms ease,
    filter 160ms ease;
}

.module:active {
  filter: brightness(0.94);
}

.module:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 6px;
}

.module-frame.is-open .module {
  border-radius: 0;
  border-color: transparent;
  background: var(--court);
  transition:
    border-radius 800ms cubic-bezier(0.22, 1, 0.36, 1),
    border-color 800ms cubic-bezier(0.22, 1, 0.36, 1),
    background-color 800ms cubic-bezier(0.22, 1, 0.36, 1);
}

.module-cover {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  transition: opacity 480ms ease;
}

.module-copy {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 48px 16px 16px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.88) 0%, rgba(0, 0, 0, 0.55) 58%, rgba(0, 0, 0, 0) 100%);
  color: #fafafa;
  transition: opacity 480ms ease;
}

.module-frame.is-open .module-cover,
.module-frame.is-open .module-copy {
  opacity: 0;
}

.module-name {
  font-size: 20px;
  font-weight: 600;
  line-height: 28px;
}

.module-description {
  color: #e5e5e5;
}

.orbit {
  position: absolute;
  inset: 0;
  overflow: visible;
  pointer-events: none;
  opacity: 0;
  transition: opacity 200ms ease;
}

.module-frame:hover .orbit,
.module-frame:focus-within .orbit,
.module-frame.is-flight .orbit {
  opacity: 1;
  transition: opacity 560ms cubic-bezier(0.22, 1, 0.36, 1);
}

.module-frame.is-open .orbit {
  opacity: 0;
  transition: opacity 240ms ease 560ms;
}

.orbit-geom {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
  color: var(--ink);
}

.particle {
  fill: none;
  stroke: currentColor;
}

@media (prefers-reduced-motion: reduce) {
  .module:hover,
  .module:focus-visible {
    border-color: var(--ink);
  }

  .orbit,
  .module-frame.is-open,
  .module-frame.is-open .module,
  .module-cover,
  .module-copy {
    animation: none;
    transition: none;
  }
}
</style>
