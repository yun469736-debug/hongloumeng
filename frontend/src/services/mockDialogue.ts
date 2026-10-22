import { defaultState } from '../data/characterStates'
import { matchCharacterState } from '../engine/stateMatcher'
import type { Character, DialogueEvent, DialogueSentenceEvent } from '../types'

type Intent = 'gentle' | 'pensive' | 'happy' | 'sad' | 'angry' | 'surprised'

const voice: Record<string, { opening: string; closing: string }> = {
  林黛玉: { opening: '你方才说的，我都听见了。', closing: '若你还愿意说，我便在这里听着。' },
  贾宝玉: { opening: '你这句话，倒叫我想了好一会儿。', closing: '咱们且慢慢说，何必拘着心意。' },
  薛宝钗: { opening: '这话我听明白了，且容我细想一层。', closing: '凡事从容些看，或许另有转圜。' },
  史湘云: { opening: '你既问到这里，我可就直说了。', closing: '说开了便好，咱们不必闷在心里。' },
  贾探春: { opening: '此事既提起来，便该看清其中关节。', closing: '把头绪理清，再作决定也不迟。' },
  贾迎春: { opening: '你的话，我在一旁静静听着呢。', closing: '我虽说得不多，却愿你心里安稳。' },
  贾惜春: { opening: '这番话听来，倒也值得静心想想。', closing: '且由它去，守住本心便是。' },
  贾元春: { opening: '你所说之事，我已经知晓。', closing: '愿你审慎自持，也莫负了自己的心。' },
  李纨: { opening: '你慢慢说来，我自会认真听着。', closing: '能彼此体谅，许多事便容易些了。' },
  妙玉: { opening: '既然问我，我便说一句。', closing: '言尽于此，你自静心体会便好。' },
  秦可卿: { opening: '你这一问，倒牵起许多未说的话。', closing: '世事如梦，眼前之意却不可轻负。' },
}

const reflection: Record<Intent, string> = {
  gentle: '你肯把这些心意说出来，已是十分难得。',
  pensive: '其中缘故并非一眼可尽，还需细细思量。',
  happy: '听来倒叫人的心里，也跟着明亮了几分。',
  sad: '这里头的难处，我听着也不免为之伤怀。',
  angry: '若事情果真如此，也实在令人难以平心。',
  surprised: '这倒出乎意料，一时竟不知该先问哪一层。',
}

const targets: Record<Intent, Pick<DialogueSentenceEvent, 'emotion' | 'action' | 'intensity'>> = {
  gentle: { emotion: '温柔', action: '凝望', intensity: .34 },
  pensive: { emotion: '沉思', action: '垂眸', intensity: .42 },
  happy: { emotion: '开心', action: '含笑', intensity: .68 },
  sad: { emotion: '伤心', action: '低眉', intensity: .82 },
  angry: { emotion: '生气', action: '正视', intensity: .86 },
  surprised: { emotion: '惊讶', action: '回望', intensity: .78 },
}

function detectIntent(text: string): Intent {
  if (/(伤心|难过|哭|眼泪|离开|失去|委屈|痛苦)/.test(text)) return 'sad'
  if (/(生气|讨厌|可恶|愤怒|不公平|欺负)/.test(text)) return 'angry'
  if (/(惊讶|竟然|没想到|真的吗|怎么会)/.test(text)) return 'surprised'
  if (/(开心|高兴|喜欢|快乐|好消息|笑)/.test(text)) return 'happy'
  if (/(为什么|如何|想一想|怎么办|觉得|认为)/.test(text)) return 'pensive'
  return 'gentle'
}

function shuffle<T>(values: T[]): T[] {
  const result = [...values]
  for (let index = result.length - 1; index > 0; index -= 1) {
    const other = Math.floor(Math.random() * (index + 1))
    ;[result[index], result[other]] = [result[other], result[index]]
  }
  return result
}

/** 一轮最多几个人真的开口。每多一人就多约 70 秒等待，这是唯一的成本开关 */
const MAX_RESPONDERS = 3

/** 提到的人就在当场时，他接话的概率。留一点余地，
 *  免得"你们谁见过宝玉"这种问法也硬把宝玉推出来答话 */
const PRESENT_MENTION_CHANCE = 0.9

export type MentionIndex = { name: string; aliases: string[] }[]

export type RoundPlan = {
  /** 这一轮真的会开口的人，按顺序 */
  responders: Character[]
  /** 被提到、且就在当场的人 */
  mentionedHere: string[]
  /** 被提到、但此刻不在场的人——只会被在席的人谈起，不会自己开口 */
  mentionedAway: string[]
}

/**
 * 排定这一轮谁开口。
 * - @ 点名且在场的人必答；
 * - 用名字或别号提到、且在场的人，很大概率接话；
 * - 提到但不在场的人不作应答者，交由在席的人去谈（后端另有提示词规则兜住）；
 * - 没人被提到时，退回原来那套随机挑 1～3 人。
 */
export function planRound(
  participants: Character[],
  mentions: MentionIndex,
  text: string,
): RoundPlan {
  if (!participants.length) {
    return { responders: [], mentionedHere: [], mentionedAway: [] }
  }

  const here = new Set(participants.map(character => character.name))
  const mentionedHere: string[] = []
  const mentionedAway: string[] = []
  for (const entry of mentions) {
    const words = [entry.name, ...entry.aliases].filter(Boolean)
    if (!words.some(word => text.includes(word))) continue
    if (here.has(entry.name)) {
      if (!mentionedHere.includes(entry.name)) mentionedHere.push(entry.name)
    } else if (!mentionedAway.includes(entry.name)) {
      mentionedAway.push(entry.name)
    }
  }

  const atMentioned = participants
    .map(character => ({ character, at: text.indexOf('@' + character.name) }))
    .filter(item => item.at >= 0)
    .sort((left, right) => left.at - right.at)
    .map(item => item.character)

  const picked: Character[] = [...atMentioned]
  for (const name of mentionedHere) {
    if (picked.length >= MAX_RESPONDERS) break
    const character = participants.find(item => item.name === name)
    if (!character || picked.includes(character)) continue
    if (Math.random() < PRESENT_MENTION_CHANCE) picked.push(character)
  }

  if (!picked.length) {
    return { responders: selectResponders(participants, text), mentionedHere, mentionedAway }
  }

  // 被点名的人先答；若还有空位，有一半机会再让一位在场的人接一句
  const rest = shuffle(participants.filter(character => !picked.includes(character)))
  const extra = rest.length && picked.length < MAX_RESPONDERS && Math.random() < 0.5 ? [rest[0]] : []
  return {
    responders: [...picked, ...extra].slice(0, MAX_RESPONDERS),
    mentionedHere,
    mentionedAway,
  }
}

export function selectResponders(participants: Character[], text: string): Character[] {
  if (participants.length <= 1) return participants

  const mentioned = participants
    .map(character => ({ character, index: text.indexOf(`@${character.name}`) }))
    .filter(item => item.index >= 0)
    .sort((left, right) => left.index - right.index)
    .map(item => item.character)

  if (mentioned.length) {
    const picked = mentioned.slice(0, MAX_RESPONDERS)
    const possibleExtras = Math.min(MAX_RESPONDERS - picked.length, 2, participants.length - picked.length)
    const extraCount = possibleExtras > 0 ? Math.floor(Math.random() * (possibleExtras + 1)) : 0
    const extras = shuffle(participants.filter(character => !picked.includes(character))).slice(0, extraCount)
    return [...picked, ...extras]
  }

  const count = 1 + Math.floor(Math.random() * Math.min(MAX_RESPONDERS, participants.length))
  return shuffle(participants).slice(0, count)
}

function sentenceEvent(character: Character, text: string, intent: Intent, currentStateId?: string): DialogueSentenceEvent {
  const target = targets[intent]
  const state = matchCharacterState(character, target, currentStateId)
  return {
    type: 'sentence',
    speaker: character.name,
    emotion: target.emotion,
    action: target.action,
    intensity: target.intensity,
    stageDirection: state.stageDirection,
    text,
  }
}

function createReply(character: Character, userText: string): DialogueEvent[] {
  const intent = detectIntent(userText)
  const firstState = matchCharacterState(character, targets.pensive)
  const middleState = matchCharacterState(character, targets[intent], firstState.id)
  const finalState = matchCharacterState(character, targets.gentle, middleState.id)
  const lines = voice[character.name]
  return [
    { type: 'speaker_start', speaker: character.name },
    sentenceEvent(character, lines.opening, 'pensive'),
    { ...sentenceEvent(character, reflection[intent], intent, firstState.id), stageDirection: middleState.stageDirection },
    { ...sentenceEvent(character, lines.closing, 'gentle', middleState.id), stageDirection: finalState.stageDirection },
    { type: 'speaker_end', speaker: character.name },
  ]
}

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const finish = () => {
      signal.removeEventListener('abort', cancel)
      resolve()
    }
    const cancel = () => {
      window.clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const timer = window.setTimeout(finish, milliseconds)
    signal.addEventListener('abort', cancel, { once: true })
  })
}

export function createMockDialogueStream(responders: Character[], userText: string, signal: AbortSignal): Response {
  const encoder = new TextEncoder()
  const events = responders.flatMap(character => createReply(character, userText))
  events.push({ type: 'round_end' })

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for (const event of events) {
          await wait(event.type === 'sentence' ? 110 : 35, signal)
          if (signal.aborted) break
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`))
        }
        controller.close()
      } catch (error) {
        if (!signal.aborted) controller.error(error)
        else controller.close()
      }
    },
  })
  return new Response(stream, { headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8' } })
}

export async function consumeNdjson(
  response: Response,
  onEvent: (event: DialogueEvent) => Promise<void>,
  signal: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error('响应不包含可读取的数据流。')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (!signal.aborted) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      await onEvent(JSON.parse(line) as DialogueEvent)
      if (signal.aborted) break
    }
    if (done) break
  }
}

export function startingStateId(character: Character): string {
  return defaultState(character).id
}
