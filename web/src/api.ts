export type Theme = 'light' | 'dark' | 'system'

export interface QiniuKeyStatus {
  configured: boolean
  hint: string | null
}

export interface SettingsResponse {
  theme: Theme
  qiniuApiKey: QiniuKeyStatus
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export interface GameModule {
  id: string
  name: string
  description: string
  coverUrl: string
}

export async function fetchModules(): Promise<GameModule[]> {
  const body = await request<{ modules: GameModule[] }>('/api/modules')
  return body.modules
}

export interface SetupRosterSeat {
  role: string
  count: number
}

export interface SetupMode {
  id: string
  title: string
  players: number
  win: string
  roster: SetupRosterSeat[]
  nightOrder: string[]
}

export interface SetupChoice {
  id: string
  title: string
  modes: string[]
}

export interface SetupOption {
  id: string
  group: string
  title: string
  detail: string
  default: string
  modes: string[]
  choices: SetupChoice[]
}

export interface SetupGroup {
  id: string
  title: string
}

export interface SetupSelection {
  mode: string
  choices: Record<string, string>
}

export interface GameSetup {
  modes: SetupMode[]
  groups: SetupGroup[]
  options: SetupOption[]
  selection: SetupSelection | null
}

export async function fetchGameSetup(moduleId: string): Promise<GameSetup> {
  return request<GameSetup>(`/api/modules/${moduleId}/setup`)
}

export async function saveGameSetup(moduleId: string, selection: SetupSelection): Promise<SetupSelection> {
  return request<SetupSelection>(`/api/modules/${moduleId}/setup`, {
    method: 'PUT',
    body: JSON.stringify(selection),
  })
}

export interface MatchMark {
  glyph: string
  color: string
}

export interface MatchSeat {
  id: number
  name: string
  mark: MatchMark
  model: string
  modelTitle: string
  alive: boolean
  speaking: boolean
  pinned: string
  exposed: boolean
  exposedRole: string
}

export interface MatchBubble {
  seatId: number | null
  name: string
  text: string
  room: string
  model?: string
  thought?: string
  note?: string
}

export interface MatchRole {
  role: string
  count: number
  title: string
}

export interface MatchMessage {
  id: number
  kind: 'thought' | 'speech' | 'system'
  seatId: number | null
  name: string
  glyph: string
  text: string
  streaming: boolean
}

export interface MatchChat {
  id: string
  title: string
  kind: 'group' | 'self'
  seatId?: number
  glyph: string
  color: string
  messages: MatchMessage[]
}

export interface XiangqiPiece {
  file: number
  rank: number
  side: 'red' | 'black'
  kind: string
  label: string
}

export interface XiangqiLastMove {
  fromFile: number
  fromRank: number
  toFile: number
  toRank: number
}

export interface MatchView {
  status: 'seating' | 'playing' | 'ended'
  mode: string
  modeTitle: string
  players: number
  call: string
  banner: string
  scene: string
  phase: string
  bubble: MatchBubble | null
  log: string[]
  roomLog: string[]
  speaking: number | null
  winner: string | null
  seats: MatchSeat[]
  roles: MatchRole[]
  canDeal: boolean
  canAdvance: boolean
  chats: MatchChat[]
  pieces?: XiangqiPiece[]
  turn?: string
  moves?: string[]
  lastMove?: XiangqiLastMove | null
}

export interface MatchStreamEvent {
  event: 'thought' | 'speech' | 'done' | 'error' | string
  data: {
    chatId?: string
    messageId?: number
    delta?: string
    name?: string
    detail?: string
    message?: MatchMessage
  } & Partial<MatchView>
}

export interface MatchMind {
  seatId: number
  name: string
  mark: MatchMark
  thoughts: { text: string }[]
  speeches: { text: string; room: string }[]
}

export interface ModelChoice {
  id: string
  title: string
}

export async function createMatch(moduleId: string): Promise<MatchView> {
  return request<MatchView>(`/api/modules/${moduleId}/match`, { method: 'POST' })
}

export async function sitDown(moduleId: string, model: string, role: string | null): Promise<MatchView> {
  return request<MatchView>(`/api/modules/${moduleId}/match/seats`, {
    method: 'POST',
    body: JSON.stringify({ model, role }),
  })
}

export async function updateSeat(
  moduleId: string,
  seatId: number,
  body: { model?: string; role?: string | null; clearRole?: boolean },
): Promise<MatchView> {
  return request<MatchView>(`/api/modules/${moduleId}/match/seats/${seatId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function removeSeat(moduleId: string, seatId: number): Promise<MatchView> {
  return request<MatchView>(`/api/modules/${moduleId}/match/seats/${seatId}`, { method: 'DELETE' })
}

export async function startMatch(moduleId: string): Promise<MatchView> {
  return request<MatchView>(`/api/modules/${moduleId}/match/start`, { method: 'POST' })
}

export async function fetchMatch(moduleId: string): Promise<MatchView> {
  return request<MatchView>(`/api/modules/${moduleId}/match`)
}

export async function advanceMatchStream(
  moduleId: string,
  onEvent: (event: MatchStreamEvent) => void,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/modules/${moduleId}/match/advance`, {
      method: 'POST',
      headers: { Accept: 'text/event-stream' },
    })
  } catch {
    throw new ApiError(0, '无法连接服务端。')
  }
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response))
  }
  if (!response.body) {
    throw new ApiError(0, '这一拍没有走下去。')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let split = buffer.indexOf('\n\n')
    while (split >= 0) {
      const parsed = parseEvent(buffer.slice(0, split))
      buffer = buffer.slice(split + 2)
      if (parsed) {
        onEvent(parsed)
      }
      split = buffer.indexOf('\n\n')
    }
  }
}

function parseEvent(block: string): MatchStreamEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).trim())
    }
  }
  if (data.length === 0) {
    return null
  }
  return { event, data: JSON.parse(data.join('\n')) as MatchStreamEvent['data'] }
}

export async function peekSeat(moduleId: string, seatId: number): Promise<{ seatId: number; name: string; role: string | null }> {
  return request(`/api/modules/${moduleId}/match/seats/${seatId}/peek`)
}

export async function fetchMind(moduleId: string, seatId: number): Promise<MatchMind> {
  return request(`/api/modules/${moduleId}/match/seats/${seatId}/mind`)
}

export async function fetchModelChoices(): Promise<ModelChoice[]> {
  try {
    const body = await request<{ data?: { id?: string }[] }>('/api/qiniu/models')
    if (!Array.isArray(body.data)) {
      return []
    }
    return body.data.flatMap((item) => (item.id ? [{ id: item.id, title: item.id }] : []))
  } catch {
    return []
  }
}

export async function fetchSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>('/api/settings')
}

export async function putTheme(theme: Theme): Promise<{ theme: Theme }> {
  return request('/api/settings/theme', {
    method: 'PUT',
    body: JSON.stringify({ theme }),
  })
}

export async function putQiniuApiKey(apiKey: string): Promise<QiniuKeyStatus> {
  return request('/api/settings/qiniu-api-key', {
    method: 'PUT',
    body: JSON.stringify({ apiKey }),
  })
}

export async function deleteQiniuApiKey(): Promise<QiniuKeyStatus> {
  return request('/api/settings/qiniu-api-key', { method: 'DELETE' })
}

export async function fetchQiniuModelCount(): Promise<number> {
  const body = await request<{ data?: unknown }>('/api/qiniu/models')
  return Array.isArray(body.data) ? body.data.length : 0
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      },
    })
  } catch {
    throw new ApiError(0, '无法连接服务端。')
  }
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response))
  }
  return response.json() as Promise<T>
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail
    }
  } catch {
    return `请求失败（${response.status}）。`
  }
  return `请求失败（${response.status}）。`
}
