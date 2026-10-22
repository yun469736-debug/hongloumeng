export type MotionPreset = 'still' | 'lower' | 'recoil' | 'lean' | 'float' | 'turn' | 'sway'

export type TransitionPreset = 'soft' | 'ink' | 'strong'

export type PortraitAlignment = {
  scale: number
  offsetX: number
  offsetY: number
}

export type CharacterState = {
  id: string
  label: string
  sourceFile: string
  image: string
  emotions: string[]
  actions: string[]
  intensity: number
  motion: MotionPreset
  stageDirection: string
  alignment: PortraitAlignment
}

export type Character = {
  id: string
  name: string
  courtesy: string
  quote: string
  available: boolean
  defaultStateId: string
  states: CharacterState[]
  /** 是否由真实 Agent 应答；当前十一位全部接通 */
  real?: boolean
}

export type Scene = {
  id: string
  name: string
  subtitle: string
  description: string
  background: string
  hotspot: [number, number]
}

/** 原著依据：随句下发，默认折叠，按需展开 */
export type Evidence = {
  chapter: number
  title: string
  quote: string
  score: number
}

export type MessageKind = '原著事实' | '性格推演' | '书外知识'

export type Message = {
  id: number
  speaker: string
  text: string
  emotion: string
  action?: string
  stageDirection?: string
  self?: boolean
  typing?: boolean
  kind?: MessageKind
  confidence?: number
  evidence?: Evidence[]
  /** 系统异常卡 */
  error?: boolean
}

export type DialogueSentenceEvent = {
  type: 'sentence'
  speaker: string
  emotion: string
  action: string
  intensity: number
  stageDirection: string
  text: string
  kind?: MessageKind
  confidence?: number
  evidence?: Evidence[]
  source?: 'agent' | 'mock'
}

/** 关系阶段变更（只给阶段，不给隐藏数值）；只有主角会发出 */
export type DialogueStageEvent = {
  type: 'stage'
  speaker: string
  stage: string
  previous?: string
  affection?: number
}

export type DialogueErrorEvent = {
  type: 'error'
  message: string
  detail?: string
}

export type DialogueControlEvent = {
  type: 'speaker_start' | 'speaker_end' | 'round_end'
  speaker?: string
  settlement?: Record<string, unknown>
}

export type DialogueEvent =
  | DialogueSentenceEvent
  | DialogueStageEvent
  | DialogueErrorEvent
  | DialogueControlEvent

export type ActorVisual = {
  state: CharacterState
  transition: TransitionPreset
  revision: number
}

/** 后端只暴露关系阶段与游戏内时间；配角 has_relationship 为 false，stage 为空 */
export type AgentState = {
  available: boolean
  character: string
  role: 'protagonist' | 'supporting'
  has_relationship: boolean
  stage: string
  stages: string[]
  game_day: number
  game_period: string
  provider?: string
  model?: string
  detail?: string
}
