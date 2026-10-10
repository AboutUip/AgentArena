import { nextTick } from 'vue'
import type { Theme } from './api'

let primed = false
let appearance = ''

function appearanceOf(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') {
    return theme
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function writeTheme(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'system') {
    delete root.dataset.theme
    return
  }
  root.dataset.theme = theme
}

export function applyTheme(theme: Theme): void {
  const next = appearanceOf(theme)
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const changed = primed && next !== appearance
  appearance = next
  primed = true
  if (!changed || reduce) {
    writeTheme(theme)
    return
  }
  const root = document.documentElement
  const start = (document as Document & {
    startViewTransition?: (update: () => void | Promise<void>) => { finished: Promise<void> }
  }).startViewTransition
  if (typeof start !== 'function') {
    writeTheme(theme)
    return
  }
  root.classList.add('theme-swap')
  try {
    const swap = start.call(document, () => {
      writeTheme(theme)
      return nextTick()
    })
    void swap.finished.finally(() => {
      root.classList.remove('theme-swap')
    })
  } catch {
    root.classList.remove('theme-swap')
    writeTheme(theme)
  }
}
