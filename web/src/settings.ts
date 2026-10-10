import { reactive } from 'vue'
import {
  deleteQiniuApiKey,
  fetchSettings,
  putQiniuApiKey,
  putTheme,
  type QiniuKeyStatus,
  type Theme,
} from './api'
import { applyTheme } from './theme'

export const settings = reactive({
  theme: 'system' as Theme,
  qiniuConfigured: false,
  qiniuHint: null as string | null,
  loaded: false,
  loadError: null as string | null,
})

export async function loadSettings(): Promise<void> {
  try {
    const data = await fetchSettings()
    settings.theme = data.theme
    applyKeyStatus(data.qiniuApiKey)
    settings.loadError = null
    applyTheme(data.theme)
  } catch (error) {
    settings.loadError = messageOf(error)
    applyTheme(settings.theme)
  } finally {
    settings.loaded = true
  }
}

export async function saveTheme(theme: Theme): Promise<void> {
  const data = await putTheme(theme)
  settings.theme = data.theme
  settings.loadError = null
  applyTheme(data.theme)
}

export async function saveQiniuApiKey(apiKey: string): Promise<void> {
  applyKeyStatus(await putQiniuApiKey(apiKey))
  settings.loadError = null
}

export async function removeQiniuApiKey(): Promise<void> {
  applyKeyStatus(await deleteQiniuApiKey())
  settings.loadError = null
}

function applyKeyStatus(status: QiniuKeyStatus): void {
  settings.qiniuConfigured = status.configured
  settings.qiniuHint = status.hint
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : '无法读取设置。'
}
