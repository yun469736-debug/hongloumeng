<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import DreamScroll from './components/DreamScroll.vue'
import MapCalibrator from './components/MapCalibrator.vue'
import PortraitActor from './components/PortraitActor.vue'
import { characters, scenes } from './data'
import { characterByName, defaultState } from './data/characterStates'
import { preloadCharacter, preloadPortrait } from './engine/portraitLoader'
import { chooseTransition, matchCharacterState } from './engine/stateMatcher'
import { consumeNdjson, createMockDialogueStream, planRound } from './services/mockDialogue'
import type { MentionIndex } from './services/mockDialogue'
import {
  DEFAULT_USER_ID,
  MOCK_MODE,
  PROTAGONIST_NAME,
  fetchAgentState,
  checkProviderKey,
  fetchCharacters,
  fetchRoomCast,
  finishAgentSession,
  getDeepseekKey,
  requestAgentDialogue,
  requestAgentGreeting,
  setDeepseekKey,
} from './services/agentClient'
import type { ProviderCheck, RoomCast } from './services/agentClient'
import type { ActorVisual, AgentState, Character, DialogueEvent, DialogueSentenceEvent, Message } from './types'

/** 一间房最多几人同席，须与后端 agent/rooms.py 的 Room.capacity 保持一致 */
const MAX_ROOM_SIZE = 5

/** 地图热区校准：?calibrate=1 打开，标定完把坐标写回 data.ts */
const calibrating = new URLSearchParams(window.location.search).get('calibrate') === '1'

const scene = ref(scenes[0])
const overview = ref(true)
const dialogueOpen = ref(true)
const mode = ref<'single' | 'group'>('group')
const selected = ref<Character[]>(characters.slice(0, 3))
const activeName = ref(PROTAGONIST_NAME)
const input = ref('')
const showRoster = ref(false)
const modal = ref<'games' | 'story' | null>(null)
/** 入梦择章：整屏覆盖，与房间互不干扰 */
const showDream = ref(false)
const isResponding = ref(false)
const currentTypingId = ref<number | null>(null)
const skipTypingId = ref<number | null>(null)
const streamError = ref('')
const assetLoading = ref<Record<string, boolean>>({})
const actionByName = ref<Record<string, string>>({})
// 开场白一律由本人开口（后端 /api/greeting）。这里不留占位台词——
// 硬塞一句别人的话，既不是他说的，也会每间房都一样。
const messages = ref<Message[]>([])
const chat = ref<HTMLElement>()
const composer = ref<HTMLTextAreaElement>()
const mentionStart = ref(-1)
const mentionQuery = ref('')
const mentionIndex = ref(0)
const expandedEvidence = ref<Set<number>>(new Set())

/** 真实 Agent：可达性与"当前焦点角色"的关系阶段（配角没有阶段） */
const agentOnline = ref(false)
const agentState = ref<AgentState | null>(null)
const thinkingSpeaker = ref<string | null>(null)
const stageNotice = ref('')
const sessionMessage = ref('')
/** 后端下发的本房名册与此刻在场人物 */
const roomCast = ref<RoomCast | null>(null)
/** 十二位人物的名字与别名，用来判断"来客这一句提到了谁"；拉不到就只认全名。
 *  注意别和 @ 候选菜单的 mentionIndex 混了，那个是键盘上下选的游标。 */
const mentionRoster = ref<MentionIndex>(characters.map(item => ({ name: item.name, aliases: [] })))

let activeController: AbortController | null = null
let greetingController: AbortController | null = null
/** 已问候过的「房间＋在场名册」签名：同一批人待在同一间房不重复开口，换房或换人才再问候 */
let greetedSignature = ''
let messageSequence = 10
let stageNoticeTimer = 0

const actorVisuals = ref<Record<string, ActorVisual>>(
  Object.fromEntries(characters.map(character => {
    const state = defaultState(character)
    actionByName.value[character.name] = state.actions[0] ?? ''
    return [character.name, { state, transition: 'soft', revision: 0 } satisfies ActorVisual]
  })),
)

const active = computed(() => characterByName.get(activeName.value) ?? selected.value[0] ?? characters[0])
const mentionCandidates = computed(() => {
  if (mentionStart.value < 0) return []
  return selected.value.filter(character => character.name.includes(mentionQuery.value))
})
const selectedNames = computed(() => new Set(selected.value.map(character => character.name)))

/** 情分轨只跟随"有七阶段关系"的角色；配角不显示 */
const stageCharacter = computed(() => {
  if (characterByName.get(activeName.value)?.real) return activeName.value
  return selected.value.find(character => character.real)?.name ?? ''
})
const hasRelationship = computed(() => agentState.value?.has_relationship === true && agentState.value?.character === stageCharacter.value)
const stageLabel = computed(() => agentState.value?.stage || '初识')
const stageIndex = computed(() => {
  const stages = agentState.value?.stages ?? []
  const found = stages.indexOf(stageLabel.value)
  return found < 0 ? 0 : found
})
const gameTimeLabel = computed(() => {
  if (!agentState.value) return '贾府 · 月上柳梢'
  return `第${agentState.value.game_day}日 · ${agentState.value.game_period}`
})
/** 用户自己填的 DeepSeek 密钥：留空用本地，有值优先走 DeepSeek */
const deepseekKey = ref(getDeepseekKey())
const usingDeepseek = computed(() => deepseekKey.value.length > 0)
const showProvider = ref(false)
const keyDraft = ref('')
const providerBusy = ref(false)
const providerNotice = ref('')
const providerOk = ref<boolean | null>(null)
const providerResult = ref<ProviderCheck | null>(null)

const agentBadge = computed(() => {
  if (MOCK_MODE) return '模拟'
  if (!agentOnline.value) return '离线'
  return usingDeepseek.value ? '真实 Agent · DeepSeek' : '真实 Agent · 本地'
})
const agentHint = computed(() => {
  if (MOCK_MODE) return '离线演示 · 同构模拟流'
  if (!agentOnline.value) return '未连接 Agent · 对话不可用'
  const model = providerResult.value?.model ?? agentState.value?.model ?? '本地模型'
  return usingDeepseek.value ? `在线 · ${model}（密钥已填）` : `在线 · ${model}`
})

function openProvider() {
  keyDraft.value = getDeepseekKey()
  providerNotice.value = ''
  providerOk.value = null
  showProvider.value = true
}

/** 保存前先校验：校验不过不落盘，免得每一轮都弹一次密钥错误 */
async function saveProviderKey() {
  providerBusy.value = true
  providerNotice.value = ''
  providerOk.value = null
  try {
    const result = await checkProviderKey(keyDraft.value)
    providerResult.value = result
    providerOk.value = result.ok
    providerNotice.value = result.message
    if (result.ok) {
      setDeepseekKey(keyDraft.value)
      deepseekKey.value = getDeepseekKey()
      await refreshAgentState()
    } else {
      providerNotice.value = `${result.message}密钥未保存，请改正后重试。`
    }
  } catch (error) {
    providerOk.value = false
    providerNotice.value = error instanceof Error ? error.message : '校验失败，后端可能未连接。'
  } finally {
    providerBusy.value = false
  }
}

function clearProviderKey() {
  keyDraft.value = ''
  setDeepseekKey('')
  deepseekKey.value = ''
  providerResult.value = null
  providerOk.value = null
  providerNotice.value = '已清除密钥，将使用本地模型。'
}

watch(
  () => selected.value.map(character => character.name).join('|'),
  () => {
    for (const character of selected.value) {
      if (assetLoading.value[character.name] !== undefined) continue
      assetLoading.value[character.name] = true
      void preloadCharacter(character.states.map(state => state.image))
        .finally(() => { assetLoading.value[character.name] = false })
    }
  },
  { immediate: true },
)

watch(stageCharacter, name => { if (name) void refreshAgentState(name) })

onMounted(() => {
  void refreshAgentState(stageCharacter.value)
  // 别名由后端一处给出，用来判断"这一句提到了谁"；拉不到就退化为只认全名
  void fetchCharacters()
    .then(list => {
      if (list.length) {
        mentionRoster.value = list.map(item => ({ name: item.name, aliases: item.aliases }))
      }
    })
    .catch(() => { /* 保持只认全名 */ })
  window.addEventListener('beforeunload', () => { void finishAgentSession(DEFAULT_USER_ID) })
})

async function refreshAgentState(character = stageCharacter.value) {
  if (MOCK_MODE || !character) {
    agentOnline.value = false
    return
  }
  try {
    const state = await fetchAgentState(DEFAULT_USER_ID, character)
    agentState.value = state
    agentOnline.value = state.available
  } catch {
    agentOnline.value = false
  }
}

function flashStage(message: string) {
  stageNotice.value = message
  window.clearTimeout(stageNoticeTimer)
  stageNoticeTimer = window.setTimeout(() => { stageNotice.value = '' }, 6000)
}

/** 离开或换院子：把这一间的对话收起来，下次进来是一间干净的屋子。
 *  注意只是不收着不显示——后端 hlm_chat 里仍按房间记着，人物照样记得。 */
function resetDialogue() {
  activeController?.abort()
  greetingController?.abort()
  activeController = null
  greetingController = null
  currentTypingId.value = null
  thinkingSpeaker.value = null
  isResponding.value = false
  streamError.value = ''
  stageNotice.value = ''
  sessionMessage.value = ''
  expandedEvidence.value = new Set()
  // 开场白等真实问候落下来；后端不可达时就空着——顶栏已经写着未连接，不必再编一句别人的台词
  messages.value = []
}

function backToMap() {
  overview.value = true
  resetDialogue()
  greetedSignature = ''
}

async function enterScene(next: typeof scene.value) {
  if (next.id !== scene.value.id) {
    resetDialogue()
    greetedSignature = '' // 换了院子就重新问候一次
  }
  scene.value = next
  overview.value = false
  await rollRoomCast(next)
  void loadGreeting()
}

/**
 * 进房先问后端"此刻这间房里都有谁"。
 * 后端按 用户＋日＋时段＋场景 播种：同一时段内反复进出结果一致，结束会谈推进时段后才换人。
 */
async function rollRoomCast(target: typeof scene.value) {
  if (MOCK_MODE || !agentOnline.value) return
  try {
    const cast = await fetchRoomCast(DEFAULT_USER_ID, target.name)
    roomCast.value = cast
    const people = cast.cast
      .map(name => characterByName.get(name))
      .filter((item): item is Character => Boolean(item))
    if (!people.length) return
    selected.value = mode.value === 'single' ? people.slice(0, 1) : people
    activeName.value = people[0].name
  } catch {
    // 后端不可达时保留当前在场人物，房间与立绘照常可用
  }
}

/** 入席问候：由名册首位开口（黛玉在场即黛玉，否则本房常驻者）；失败则保留原开场白 */
async function loadGreeting() {
  if (MOCK_MODE || !agentOnline.value) return
  const speaker = selected.value[0]
  if (!speaker) return
  const signature = scene.value.name + '|' + selected.value.map(item => item.name).join(',')
  if (signature === greetedSignature) return
  greetedSignature = signature

  const controller = new AbortController()
  greetingController = controller
  thinkingSpeaker.value = speaker.name
  await scrollToBottom()

  try {
    const response = await requestAgentGreeting({
      user_id: DEFAULT_USER_ID,
      text: '',
      speaker: speaker.name,
      present_characters: selected.value.map(character => character.name),
      scene: scene.value.name,
      greeting_kind: 'room',
    }, controller.signal)

    let first = true
    await consumeNdjson(response, async event => {
      if (event.type === 'sentence' && first) {
        first = false
      }
      await handleDialogueEvent(event, controller.signal)
    }, controller.signal)
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) agentOnline.value = false
  } finally {
    if (greetingController === controller) greetingController = null
    if (thinkingSpeaker.value === speaker.name) thinkingSpeaker.value = null
  }
}

/**
 * 入席与离席的一句话。
 *
 * 说话人由 speaker 显式指定——请离时那个人已经不在名单里了，
 * 只按名单首位找的话会由别人替他开口。
 */
async function speakOnShift(name: string, kind: 'entry' | 'leave') {
  if (MOCK_MODE || !agentOnline.value || isResponding.value) return
  if (!characterByName.get(name)) return

  const controller = new AbortController()
  activeController = controller
  isResponding.value = true
  thinkingSpeaker.value = name
  await scrollToBottom()

  try {
    const response = await requestAgentGreeting({
      user_id: DEFAULT_USER_ID,
      text: '',
      speaker: name,
      present_characters: selected.value.map(item => item.name),
      scene: scene.value.name,
      greeting_kind: kind,
    }, controller.signal)
    await consumeNdjson(response, event => handleDialogueEvent(event, controller.signal), controller.signal)
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) {
      streamError.value = error instanceof Error ? error.message : `${name}一时未能开口。`
    }
  } finally {
    if (activeController === controller) activeController = null
    thinkingSpeaker.value = null
    isResponding.value = false
  }
}

function chooseCharacter(character: Character) {
  if (isResponding.value) return
  const exists = selectedNames.value.has(character.name)
  if (mode.value === 'single') {
    selected.value = [character]
    activeName.value = character.name
    showRoster.value = false
    return
  }
  if (exists) {
    if (selected.value.length > 1) removeCharacter(character.name)
    return
  }
  if (selected.value.length >= MAX_ROOM_SIZE) return
  selected.value = [...selected.value, character]
  activeName.value = character.name
  void speakOnShift(character.name, 'entry')
}

function removeCharacter(name: string) {
  if (isResponding.value || selected.value.length === 1) return
  selected.value = selected.value.filter(item => item.name !== name)
  if (activeName.value === name) activeName.value = selected.value[0].name
  // 名单先去掉他再请他作别：present 是剩下的人，说话人由 speaker 指定
  void speakOnShift(name, 'leave')
}

function setMode(next: 'single' | 'group') {
  if (isResponding.value) return
  mode.value = next
  if (next === 'single') selected.value = [active.value]
}

function updateMention() {
  const textarea = composer.value
  if (!textarea) return
  const cursor = textarea.selectionStart
  const match = input.value.slice(0, cursor).match(/@([^@\s，。！？]*)$/)
  if (!match) {
    mentionStart.value = -1
    mentionQuery.value = ''
    return
  }
  mentionStart.value = cursor - match[0].length
  mentionQuery.value = match[1]
  mentionIndex.value = 0
}

async function insertMention(name: string) {
  const textarea = composer.value
  if (!textarea || mentionStart.value < 0) return
  const cursor = textarea.selectionStart
  const nextCursor = mentionStart.value + name.length + 2
  input.value = `${input.value.slice(0, mentionStart.value)}@${name} ${input.value.slice(cursor)}`
  mentionStart.value = -1
  await nextTick()
  textarea.focus()
  textarea.setSelectionRange(nextCursor, nextCursor)
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (mentionCandidates.value.length) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      mentionIndex.value = (mentionIndex.value + 1) % mentionCandidates.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      mentionIndex.value = (mentionIndex.value - 1 + mentionCandidates.value.length) % mentionCandidates.value.length
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void insertMention(mentionCandidates.value[mentionIndex.value].name)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      mentionStart.value = -1
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

function abortableWait(milliseconds: number, signal: AbortSignal): Promise<void> {
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

async function scrollToBottom() {
  await nextTick()
  chat.value?.scrollTo({ top: chat.value.scrollHeight, behavior: 'smooth' })
}

function toggleEvidence(id: number) {
  const next = new Set(expandedEvidence.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedEvidence.value = next
}

function pushCard(card: Omit<Message, 'id'>) {
  messages.value.push({ ...card, id: ++messageSequence })
}

async function playSentence(event: DialogueSentenceEvent, signal: AbortSignal) {
  const character = characterByName.get(event.speaker)
  if (!character) return

  activeName.value = character.name
  const currentVisual = actorVisuals.value[character.name]
  const nextState = matchCharacterState(character, event, currentVisual.state.id)
  const stateChanged = nextState.id !== currentVisual.state.id

  if (stateChanged) {
    try {
      await preloadPortrait(nextState.image)
      if (signal.aborted) return
      actorVisuals.value = {
        ...actorVisuals.value,
        [character.name]: {
          state: nextState,
          transition: chooseTransition(currentVisual.state, nextState),
          revision: currentVisual.revision + 1,
        },
      }
    } catch {
      streamError.value = `${character.name}的"${nextState.label}"立绘未能载入，已保持上一状态。`
    }
  }

  await abortableWait(stateChanged ? 200 : 90, signal)
  const resolvedAction = nextState.actions[0] ?? event.action
  const actionChanged = actionByName.value[character.name] !== resolvedAction
  if (actionChanged) actionByName.value[character.name] = resolvedAction

  const id = ++messageSequence
  const message: Message = {
    id,
    speaker: event.speaker,
    emotion: event.emotion,
    action: resolvedAction,
    stageDirection: actionChanged ? nextState.stageDirection : undefined,
    text: '',
    typing: true,
    kind: event.kind,
    confidence: event.confidence,
    evidence: event.evidence,
  }
  messages.value.push(message)
  currentTypingId.value = id
  await scrollToBottom()

  const charactersInLine = Array.from(event.text)
  for (let index = 0; index < charactersInLine.length; index += 1) {
    if (signal.aborted) break
    if (skipTypingId.value === id) {
      message.text = event.text
      skipTypingId.value = null
      break
    }
    message.text += charactersInLine[index]
    if (index % 7 === 0) await scrollToBottom()
    const punctuationPause = /[，。！？；]/.test(charactersInLine[index]) ? 75 : 0
    await abortableWait(30 + punctuationPause, signal)
  }
  message.typing = false
  currentTypingId.value = null
  await scrollToBottom()
}

async function handleDialogueEvent(event: DialogueEvent, signal: AbortSignal) {
  if (event.type === 'speaker_start' && event.speaker) activeName.value = event.speaker
  if (event.type === 'sentence') {
    await playSentence(event, signal)
    return
  }
  if (event.type === 'stage') {
    // 只有主角会发 stage 事件；若当前焦点已切到别人则不打扰界面
    if (!agentState.value || agentState.value.character !== event.speaker) return
    const previous = agentState.value.stage
    agentState.value = { ...agentState.value, stage: event.stage }
    if (previous && previous !== event.stage) {
      flashStage(`${event.speaker}的情分：${previous} → ${event.stage}`)
    }
    return
  }
  if (event.type === 'error') {
    pushCard({
      speaker: '系统',
      emotion: '',
      text: `${event.message}${event.detail ? `（${event.detail}）` : ''}`,
      error: true,
    })
    await scrollToBottom()
  }
}

function skipCurrentMessage(message: Message) {
  if (message.typing) skipTypingId.value = message.id
}

function stopPlayback() {
  activeController?.abort()
  greetingController?.abort()
  activeController = null
  greetingController = null
  const typing = messages.value.find(message => message.id === currentTypingId.value)
  if (typing) typing.typing = false
  currentTypingId.value = null
  thinkingSpeaker.value = null
  isResponding.value = false
}

async function send() {
  const text = input.value.trim()
  if (!text || isResponding.value) return

  greetingController?.abort()
  greetingController = null

  mentionStart.value = -1
  streamError.value = ''
  messages.value.push({ id: ++messageSequence, speaker: '我', emotion: '', text, self: true })
  input.value = ''
  await scrollToBottom()

  // 谁开口：@ 点名与"提到且就在当场"的人优先，其余随机补位；
  // 提到但不在场的人不会被当成应答者，交由在席的人去谈。
  const plan = planRound(selected.value, mentionRoster.value, text)
  const responders = plan.responders
  const controller = new AbortController()
  activeController = controller
  isResponding.value = true

  try {
    for (const [roundIndex, character] of responders.entries()) {
      if (controller.signal.aborted) break

      if (MOCK_MODE) {
        const response = createMockDialogueStream([character], text, controller.signal)
        await consumeNdjson(response, event => handleDialogueEvent(event, controller.signal), controller.signal)
        continue
      }

      thinkingSpeaker.value = character.name
      activeName.value = character.name
      await scrollToBottom()

      let response: Response
      try {
        response = await requestAgentDialogue({
          user_id: DEFAULT_USER_ID,
          text,
          speaker: character.name,
          present_characters: selected.value.map(item => item.name),
          scene: scene.value.name,
          round_index: roundIndex,
        }, controller.signal)
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') break
        agentOnline.value = false
        thinkingSpeaker.value = null
        pushCard({
          speaker: '系统',
          emotion: '',
          text: `未能连上真实 Agent，${character.name}本轮没有回应。房间与立绘仍在，可稍后再试。`,
          error: true,
        })
        continue
      }
      thinkingSpeaker.value = null
      await consumeNdjson(response, event => handleDialogueEvent(event, controller.signal), controller.signal)
    }
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) {
      streamError.value = error instanceof Error ? error.message : '对话流发生错误。'
    }
  } finally {
    if (activeController === controller) activeController = null
    const typing = messages.value.find(message => message.id === currentTypingId.value)
    if (typing) typing.typing = false
    currentTypingId.value = null
    thinkingSpeaker.value = null
    isResponding.value = false
    await refreshAgentState()
  }
}

async function endSession() {
  sessionMessage.value = '正在结算会谈……'
  try {
    await finishAgentSession(DEFAULT_USER_ID)
    await refreshAgentState()
    sessionMessage.value = '本次会谈已结算，时候又进了一段。'
  } catch {
    sessionMessage.value = '结算未成功，Agent 可能未连接。'
  }
  window.setTimeout(() => { sessionMessage.value = '' }, 6000)
}
</script>

<template>
  <MapCalibrator v-if="calibrating" />

  <main v-else class="mansion" :class="{ overview, 'dialogue-collapsed': !dialogueOpen }" :style="overview ? {} : { backgroundImage: `linear-gradient(rgba(20,24,21,.18),rgba(20,24,21,.28)), url('/assets/buildings/${scene.background}')` }">
    <header class="topbar">
      <div class="brand"><span class="seal">梦</span><div><h1>大观清谈</h1><p>红楼人物雅集</p></div></div>
      <button
        class="agent-status"
        :class="{ online: agentOnline && !MOCK_MODE, cloud: usingDeepseek }"
        title="点击设置 DeepSeek 密钥（留空则用本地模型）"
        @click="openProvider"
      >
        <span class="dot"></span>
        <div><b>{{ agentBadge }}</b><small>{{ agentHint }}</small></div>
        <i class="caret">设置</i>
      </button>
      <div class="time"><i></i> 贾府 · {{ gameTimeLabel }}</div>
      <button class="text-button" @click="showRoster = true">人物名册</button>
    </header>

    <section v-if="overview" class="estate-map">
      <div class="map-canvas">
        <img src="/assets/buildings/贾府.png" alt="贾府全图">
        <button
          v-for="item in scenes"
          :key="item.id"
          class="map-hotspot"
          :style="{ left: item.hotspot[0] + '%', top: item.hotspot[1] + '%' }"
          :aria-label="`进入${item.name}`"
          @click="enterScene(item)"
        ><span>{{ item.name }}</span></button>
      </div>
      <div class="map-guide"><span>贾府全图</span><h2>择一院落入园</h2><p>点击图中院落名称，进入相应场景</p></div>
    </section>

    <nav v-else class="scene-tabs" aria-label="贾府场景">
      <button class="back-map" @click="backToMap"><span>返回贾府全图</span><small>重择院落</small></button>
      <button v-for="item in scenes" :key="item.id" :class="{ active: scene.id === item.id }" @click="enterScene(item)">
        <span>{{ item.name }}</span><small>{{ item.subtitle }}</small>
      </button>
    </nav>

    <section v-if="!overview" class="scene-intro">
      <span>此间</span><h2>{{ scene.name }}</h2><p>{{ scene.description }}</p>
      <div v-if="roomCast" class="cast-note">
        <p v-if="roomCast.residents.length"><b>常驻</b>{{ roomCast.residents.join('、') }}</p>
        <p v-if="roomCast.guests.length"><b>访客</b>{{ roomCast.guests.join('、') }}</p>
        <p v-if="roomCast.mention_only.length"><b>仅可提及</b>{{ roomCast.mention_only.join('、') }}</p>
        <p class="daiyu" :class="{ here: roomCast.daiyu_present }">
          黛玉{{ roomCast.daiyu_present ? '在场' : '不在场' }} · 本处约 {{ Math.round(roomCast.daiyu_chance * 100) }}%
        </p>
      </div>
    </section>

    <section v-if="!overview" class="character-stage" :class="`count-${selected.length}`">
      <PortraitActor
        v-for="character in selected"
        :key="character.name"
        :character="character"
        :visual="actorVisuals[character.name]"
        :speaking="activeName === character.name"
        :loading="assetLoading[character.name]"
        :removable="selected.length > 1"
        @activate="activeName = character.name"
        @remove="removeCharacter(character.name)"
      />
      <button v-if="mode === 'group' && selected.length < MAX_ROOM_SIZE" class="invite" @click="showRoster = true"><b>＋</b><span>邀人入席</span></button>
    </section>

    <aside v-if="!overview" class="dialogue-scroll" :class="{ collapsed: !dialogueOpen }">
      <button class="scroll-toggle" :aria-label="dialogueOpen ? '收起对话卷轴' : '展开对话卷轴'" :title="dialogueOpen ? '收起对话' : '展开对话'" @click="dialogueOpen = !dialogueOpen">
        <span>{{ dialogueOpen ? '收卷' : '展卷' }}</span>
      </button>
      <div v-show="dialogueOpen" class="scroll-head">
        <div><span>雅集 · {{ scene.name }}</span><h3>{{ mode === 'group' ? '众芳清谈' : `与${active.name}清谈` }}</h3></div>
        <div class="mode-switch"><button :class="{ active: mode === 'single' }" :disabled="isResponding" @click="setMode('single')">独叙</button><button :class="{ active: mode === 'group' }" :disabled="isResponding" @click="setMode('group')">雅集</button></div>
      </div>

      <div v-if="hasRelationship" v-show="dialogueOpen" class="stage-track">
        <span class="track-label">{{ agentState?.character }} · 情分</span>
        <ol>
          <li v-for="(item, index) in (agentState?.stages ?? [])" :key="item" :class="{ reached: index <= stageIndex, current: index === stageIndex }">{{ item }}</li>
        </ol>
        <button class="session-button" :disabled="!agentOnline" @click="endSession">结束会谈</button>
      </div>
      <p v-if="stageNotice" class="stage-notice">{{ stageNotice }}</p>
      <p v-if="sessionMessage" class="session-notice">{{ sessionMessage }}</p>

      <div v-show="dialogueOpen" ref="chat" class="messages" aria-live="polite">
        <div v-for="message in messages" :key="message.id" class="message" :class="{ self: message.self, typing: message.typing, error: message.error }" @click="skipCurrentMessage(message)">
          <template v-if="message.error">
            <div class="speaker error-speaker">{{ message.speaker }}</div>
            <div class="error-card">{{ message.text }}</div>
          </template>
          <template v-else>
            <div class="speaker">
              {{ message.speaker }}
              <em v-if="message.emotion">{{ message.emotion }}</em>
              <span v-if="message.kind" class="kind-tag" :class="`kind-${message.kind === '原著事实' ? 'fact' : message.kind === '书外知识' ? 'outside' : 'infer'}`">{{ message.kind }}</span>
            </div>
            <div v-if="message.stageDirection" class="stage-direction">（{{ message.stageDirection }}）</div>
            <p>{{ message.text }}<i v-if="message.typing" class="typing-caret"></i></p>
            <div v-if="message.evidence?.length" class="evidence-block">
              <button class="evidence-toggle" @click.stop="toggleEvidence(message.id)">
                原著依据 · {{ message.evidence.length }} 条
                <span v-if="message.confidence !== undefined">（相关度 {{ message.confidence.toFixed(2) }}）</span>
                <b>{{ expandedEvidence.has(message.id) ? '收起' : '展开' }}</b>
              </button>
              <ul v-if="expandedEvidence.has(message.id)" class="evidence-list">
                <li v-for="entry in message.evidence" :key="`${message.id}-${entry.chapter}-${entry.quote.slice(0, 8)}`">
                  <span>第{{ entry.chapter }}回 {{ entry.title }}</span>
                  <q>{{ entry.quote }}</q>
                </li>
              </ul>
            </div>
          </template>
        </div>
        <p v-if="thinkingSpeaker" class="thinking-line"><i></i>{{ thinkingSpeaker }}正在斟酌语句……</p>
        <p v-if="streamError" class="stream-error">{{ streamError }}</p>
      </div>

      <div v-show="dialogueOpen" class="composer">
        <div v-if="mentionCandidates.length" class="mention-menu" role="listbox" aria-label="选择在场人物">
          <button
            v-for="(candidate, index) in mentionCandidates"
            :key="candidate.name"
            :class="{ active: index === mentionIndex }"
            role="option"
            @mousedown.prevent="insertMention(candidate.name)"
          >@{{ candidate.name }}<small>{{ candidate.courtesy }}</small></button>
        </div>
        <textarea
          ref="composer"
          v-model="input"
          :disabled="isResponding"
          placeholder="落笔说些什么，输入 @ 可点名……"
          @input="updateMention"
          @click="updateMention"
          @keyup.left="updateMention"
          @keyup.right="updateMention"
          @keydown="handleComposerKeydown"
        ></textarea>
        <div>
          <span>{{ isResponding ? (thinkingSpeaker ? `${thinkingSpeaker}正在反应（真实 Agent，请稍候）` : '正在播放 · 点击台词可加速') : 'Enter 送出 · Shift + Enter 换行' }}</span>
          <button v-if="isResponding" class="stop-button" @click="stopPlayback">止语</button>
          <button v-else :disabled="!input.trim()" @click="send">寄语</button>
        </div>
      </div>
    </aside>

    <footer v-if="!overview" class="activity-dock">
      <button @click="modal = 'games'"><span>令</span><div><b>飞花令</b><small>以诗会友</small></div></button>
      <button @click="showDream = true"><span>回</span><div><b>入梦择章</b><small>重走原著</small></div></button>
      <div class="present"><i v-for="person in selected" :key="person.name">{{ person.name.slice(-1) }}</i><p>{{ selected.length }} 位人物在席</p></div>
    </footer>

    <Transition name="veil">
      <div v-if="showRoster" class="overlay" @click.self="showRoster = false">
        <section class="roster panel"><button class="close" @click="showRoster = false">×</button><span class="eyebrow">金陵人物册</span><h2>邀谁入园一叙？</h2>
          <p class="roster-hint">雅集可邀 1～{{ MAX_ROOM_SIZE }} 位人物。已入席 {{ selected.length }}/{{ MAX_ROOM_SIZE }}，点击已选人物可请其离席。十二位皆由真实 Agent 应答；林黛玉为主角，余者为配角。一轮通常由 1～3 人开口。</p>
          <div class="roster-grid"><button
            v-for="person in characters"
            :key="person.name"
            :class="{ selected: selectedNames.has(person.name) }"
            :disabled="isResponding || (mode === 'group' && selected.length >= MAX_ROOM_SIZE && !selectedNames.has(person.name))"
            @click="chooseCharacter(person)"
          >
            <img :src="defaultState(person).image" :alt="person.name"><span v-if="selectedNames.has(person.name)" class="selected-mark">在席</span>
            <strong>{{ person.name }}</strong><small>{{ person.courtesy }}</small>
          </button></div>
        </section>
      </div>
    </Transition>

    <Transition name="veil">
      <div v-if="showProvider" class="overlay" @click.self="showProvider = false">
        <section class="panel provider-panel">
          <button class="close" @click="showProvider = false">×</button>
          <span class="eyebrow">模型来源</span>
          <h2>真实 Agent 用哪个模型</h2>
          <p class="provider-note">
            留空则用本机的 Ollama 模型。填入你自己的 DeepSeek 密钥后优先走 DeepSeek；
            密钥有误会在这里当场提示，并继续用本地模型，不会让对话中断。
          </p>
          <label class="provider-field">
            <span>DeepSeek 密钥</span>
            <input
              v-model="keyDraft"
              type="password"
              autocomplete="off"
              spellcheck="false"
              placeholder="sk-…（留空即用本地模型）"
              @keydown.enter="saveProviderKey"
            >
          </label>
          <p
            v-if="providerNotice"
            class="provider-result"
            :class="{ bad: providerOk === false, good: providerOk === true }"
          >{{ providerNotice }}</p>
          <div class="provider-actions">
            <button class="primary" :disabled="providerBusy" @click="saveProviderKey">
              {{ providerBusy ? '正在校验…' : '保存并测试' }}
            </button>
            <button :disabled="providerBusy" @click="clearProviderKey">清除密钥</button>
          </div>
          <p class="provider-hint">
            密钥只存在本机浏览器的 localStorage，只发给本机后端；不写入仓库、数据库或日志。
            校验不通过时不会保存，免得每一轮都弹一次密钥错误。
          </p>
        </section>
      </div>
    </Transition>

    <DreamScroll v-if="showDream" @close="showDream = false" />

    <Transition name="veil"><div v-if="modal" class="overlay" @click.self="modal = null"><section class="game panel"><button class="close" @click="modal = null">×</button>
      <span class="eyebrow">诗社雅令</span><h2>飞花令</h2>
      <p>拈一字为令，与在席人物轮番吟诗。下一版本将由 Agent 判断诗句、接续回合。</p>
      <div class="coming">下个版本开放</div>
    </section></div></Transition>
  </main>
</template>
