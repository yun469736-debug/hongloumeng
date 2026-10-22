import type { AgentState, DialogueEvent } from '../types'

const RAW_BASE = (import.meta.env?.VITE_AGENT_BASE as string | undefined) ?? ''
/** 默认走同源 /api，由 vite 代理到本地 FastAPI；可用 VITE_AGENT_BASE 覆盖 */
export const AGENT_BASE = RAW_BASE.replace(/\/$/, '')
export const DEFAULT_USER_ID = 'local_default'
/** 主角：只有她拥有七阶段关系、私有记忆与入席问候 */
export const PROTAGONIST_NAME = '林黛玉'
/** 调试开关：后端未起时用同构模拟流演示界面，默认关闭 */
export const MOCK_MODE = ((import.meta.env?.VITE_AGENT_MOCK as string | undefined) ?? '') === '1'

export type DialoguePayload = {
  user_id: string
  text: string
  /** 显式声明本轮由谁应答 */
  speaker: string
  present_characters: string[]
  scene?: string
  /** 只在问候接口上有意义：room 进院、entry 被邀入席、leave 离席 */
  greeting_kind?: 'room' | 'entry' | 'leave'
  /** 本轮里的第几个开口（0 起）。大于 0 时后端会隐去同轮前面人的答复 */
  round_index?: number
}

/* ------------------------------------------------------------------ DeepSeek 密钥
 * 只存在本机浏览器的 localStorage 里，只随请求发给本机后端，绝不写进仓库或数据库。
 * 留空 = 用本地 Ollama；填了 = 优先 DeepSeek，密钥无效时后端会先报错再退回本地。
 */

const KEY_STORAGE = 'hlm.deepseekKey'

export function getDeepseekKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) ?? ''
  } catch {
    return '' // 隐私模式下 localStorage 不可用，按未填处理
  }
}

export function setDeepseekKey(key: string): void {
  try {
    const trimmed = key.trim()
    if (trimmed) localStorage.setItem(KEY_STORAGE, trimmed)
    else localStorage.removeItem(KEY_STORAGE)
  } catch {
    /* 同上：写不进去也不该让界面崩 */
  }
}

function keyHeaders(): Record<string, string> {
  const key = getDeepseekKey()
  return key ? { 'X-DeepSeek-Key': key } : {}
}

/* ------------------------------------------------------------------ 入梦择章 */

export type DreamChapter = {
  key: string
  title: string
  chapters: string
  cast: string[]
  invoker: string
  node_count: number
  segment_count: number
  status: 'new' | 'started' | 'finished'
  segment_index: number
  settled: boolean
}

export type DreamOption = { key: string; text: string; basis: string }

export type DreamNode = {
  key: string
  title: string
  situation: string
  options: DreamOption[]
}

export type DreamContext = {
  chapter: DreamChapter
  segment_index: number
  segment_total: number
  text: string
  finished: boolean
  exit_line: string
  cast: string[]
  choices: Record<string, string>
  node: DreamNode | null
}

async function postJson(path: string, body: unknown): Promise<Response> {
  const response = await fetch(`${AGENT_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...keyHeaders() },
    body: JSON.stringify(body),
  })
  if (!response.ok || !response.body) throw new Error(`Agent 接口返回 ${response.status}`)
  return response
}

export async function fetchDreamList(userId = DEFAULT_USER_ID): Promise<DreamChapter[]> {
  const response = await fetch(`${AGENT_BASE}/api/dream/list?user_id=${encodeURIComponent(userId)}`)
  if (!response.ok) throw new Error(`入梦目录返回 ${response.status}`)
  const data = (await response.json()) as { chapters: DreamChapter[] }
  return data.chapters ?? []
}

export function enterDream(
  userId: string,
  chapterKey: string,
  cast: string[] = [],
  restart = false,
): Promise<Response> {
  return postJson('/api/dream/enter', {
    user_id: userId,
    chapter_key: chapterKey,
    cast,
    restart,
  })
}

export function chooseDream(
  userId: string,
  chapterKey: string,
  nodeKey: string,
  optionKey: string,
): Promise<Response> {
  return postJson('/api/dream/choose', {
    user_id: userId,
    chapter_key: chapterKey,
    node_key: nodeKey,
    option_key: optionKey,
  })
}

export async function leaveDream(userId: string, chapterKey: string): Promise<void> {
  await postJson('/api/dream/leave', { user_id: userId, chapter_key: chapterKey })
}

export type CharacterMention = {
  name: string
  courtesy: string
  aliases: string[]
  role: 'protagonist' | 'supporting'
}

/** 十二位人物的名字与常用称呼；别名由后端一处给出，前端不另存一份 */
export async function fetchCharacters(): Promise<CharacterMention[]> {
  const response = await fetch(`${AGENT_BASE}/api/characters`)
  if (!response.ok) throw new Error(`人物接口返回 ${response.status}`)
  const data = (await response.json()) as { characters: CharacterMention[] }
  return data.characters ?? []
}

export type ProviderCheck = {
  ok: boolean
  provider: 'ollama' | 'deepseek'
  model: string
  detail: string
  message: string
}

/** 校验密钥。空密钥不算错误，只表示"用本地"。 */
export async function checkProviderKey(key = getDeepseekKey()): Promise<ProviderCheck> {
  const trimmed = key.trim()
  const response = await fetch(`${AGENT_BASE}/api/provider/check`, {
    method: 'POST',
    headers: trimmed ? { 'X-DeepSeek-Key': trimmed } : {},
  })
  if (!response.ok) throw new Error(`密钥校验接口返回 ${response.status}`)
  return (await response.json()) as ProviderCheck
}

async function postNdjson(path: string, payload: DialoguePayload, signal: AbortSignal): Promise<Response> {
  const response = await fetch(`${AGENT_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...keyHeaders() },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`Agent 接口返回 ${response.status}`)
  }
  return response
}

export function requestAgentDialogue(payload: DialoguePayload, signal: AbortSignal): Promise<Response> {
  return postNdjson('/api/dialogue', payload, signal)
}

export function requestAgentGreeting(payload: DialoguePayload, signal: AbortSignal): Promise<Response> {
  return postNdjson('/api/greeting', payload, signal)
}

/** 这间房此刻有谁；由后端按 用户＋日＋时段＋场景 播种，同一时段内反复进出结果一致 */
export type RoomCast = {
  ok: boolean
  scene: string
  cast: string[]
  greeter: string
  residents: string[]
  guests: string[]
  mention_only: string[]
  daiyu_present: boolean
  daiyu_chance: number
  known_room: boolean
  seed: { user_id: string; game_day: number; game_period: string; scene: string }
}

export async function fetchRoomCast(
  userId = DEFAULT_USER_ID,
  scene = '',
): Promise<RoomCast> {
  const response = await fetch(
    `${AGENT_BASE}/api/room?user_id=${encodeURIComponent(userId)}&scene=${encodeURIComponent(scene)}`,
  )
  if (!response.ok) throw new Error(`在场人物接口返回 ${response.status}`)
  return (await response.json()) as RoomCast
}

export async function fetchAgentState(
  userId = DEFAULT_USER_ID,
  character = PROTAGONIST_NAME,
): Promise<AgentState> {
  const response = await fetch(
    `${AGENT_BASE}/api/state?user_id=${encodeURIComponent(userId)}&character=${encodeURIComponent(character)}`,
  )
  if (!response.ok) throw new Error(`状态接口返回 ${response.status}`)
  return (await response.json()) as AgentState
}

export async function finishAgentSession(userId = DEFAULT_USER_ID): Promise<void> {
  await fetch(`${AGENT_BASE}/api/session/end`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, text: '', speaker: PROTAGONIST_NAME, present_characters: [] }),
  })
}

export type { DialogueEvent }
