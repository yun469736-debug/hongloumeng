<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { consumeNdjson } from '../services/mockDialogue'
import {
  DEFAULT_USER_ID,
  chooseDream,
  enterDream,
  fetchDreamList,
  leaveDream,
} from '../services/agentClient'
import type { DreamChapter, DreamContext, DreamNode } from '../services/agentClient'

const emit = defineEmits<{ (event: 'close'): void }>()

type Line = { id: number; speaker: string; emotion: string; action: string; text: string; error?: boolean }

const chapters = ref<DreamChapter[]>([])
const listError = ref('')
const busy = ref(false)
const scene = ref<'list' | 'dream'>('list')

const chapter = ref<DreamChapter | null>(null)
const segment = ref<DreamContext | null>(null)
const lines = ref<Line[]>([])
const picked = ref('')
const pickedNode = ref('')
const scroll = ref<HTMLElement>()
let sequence = 0

const node = computed<DreamNode | null>(() => segment.value?.node ?? null)
const segmentsTotal = computed(() => segment.value?.segment_total ?? 3)
const segmentNo = computed(() => (segment.value?.segment_index ?? 0) + 1)

async function scrollDown() {
  await nextTick()
  scroll.value?.scrollTo({ top: scroll.value.scrollHeight, behavior: 'smooth' })
}

function push(line: Omit<Line, 'id'>) {
  lines.value.push({ ...line, id: ++sequence })
}

async function loadList() {
  listError.value = ''
  try {
    chapters.value = await fetchDreamList(DEFAULT_USER_ID)
  } catch (error) {
    listError.value = error instanceof Error ? error.message : '读不到章节列表，后端可能未连接。'
  }
}

async function handleEvent(event: Record<string, unknown>) {
  const type = event.type
  if (type === 'sentence') {
    push({
      speaker: String(event.speaker ?? ''),
      emotion: String(event.emotion ?? ''),
      action: String(event.action ?? ''),
      text: String(event.text ?? ''),
    })
    void scrollDown()
    return
  }
  if (type === 'dream') {
    segment.value = event as unknown as DreamContext
    picked.value = ''
    pickedNode.value = segment.value.node?.key ?? ''
    void scrollDown()
    return
  }
  if (type === 'error') {
    push({ speaker: '系统', emotion: '', action: '', text: String(event.message ?? ''), error: true })
    void scrollDown()
  }
}

async function enter(key: string, restart = false) {
  busy.value = true
  lines.value = []
  chapter.value = chapters.value.find(item => item.key === key) ?? null
  scene.value = 'dream'
  try {
    const response = await enterDream(DEFAULT_USER_ID, key, [], restart)
    await consumeNdjson(response, event => handleEvent(event as Record<string, unknown>), new AbortController().signal)
  } catch (error) {
    push({ speaker: '系统', emotion: '', action: '', text: error instanceof Error ? error.message : '入梦失败。', error: true })
  } finally {
    busy.value = false
    void loadList()
  }
}

function enterFrom(item: DreamChapter) {
  const replay = item.status === 'finished'
  if (replay && !window.confirm('这一章已经走过一遍。再走一遍不会重复改变他们对你的看法，确定？')) return
  void enter(item.key, replay)
}

async function choose(optionKey: string) {
  if (!chapter.value || !node.value || busy.value) return
  busy.value = true
  picked.value = optionKey
  const option = node.value.options.find(item => item.key === optionKey)
  push({ speaker: '我', emotion: '', action: '', text: option?.text ?? '' })
  await scrollDown()
  try {
    const response = await chooseDream(DEFAULT_USER_ID, chapter.value.key, node.value.key, optionKey)
    await consumeNdjson(response, event => handleEvent(event as Record<string, unknown>), new AbortController().signal)
  } catch (error) {
    push({ speaker: '系统', emotion: '', action: '', text: error instanceof Error ? error.message : '这一步没能走下去。', error: true })
  } finally {
    busy.value = false
    void loadList()
  }
}

async function quit() {
  if (chapter.value && scene.value === 'dream') {
    try {
      await leaveDream(DEFAULT_USER_ID, chapter.value.key)
    } catch {
      /* 退出失败不该挡住人离开 */
    }
  }
  scene.value = 'list'
  lines.value = []
  segment.value = null
  void loadList()
}

onMounted(loadList)
</script>

<template>
  <section class="dream">
    <header class="dream-bar">
      <span class="eyebrow">太虚一梦</span>
      <b>{{ scene === 'list' ? '入梦择章' : chapter?.title }}</b>
      <small v-if="scene === 'dream'">第{{ chapter?.chapters }}回 · 第 {{ segmentNo }} / {{ segmentsTotal }} 段</small>
      <button v-if="scene === 'dream'" class="ghost" @click="quit">出梦</button>
      <button v-else class="ghost" @click="emit('close')">合卷</button>
    </header>

    <div v-if="scene === 'list'" class="dream-list">
      <p class="dream-hint">
        走入原著的一段关目，听在场人物各陈心意，再替故事作一次选择。
        梦里可以选、可以变；醒来原著一字不改，留下的是他们对你的心绪与看法。
      </p>
      <p v-if="listError" class="dream-error">{{ listError }}</p>
      <div class="dream-grid">
        <button
          v-for="item in chapters"
          :key="item.key"
          :class="{ done: item.status === 'finished', going: item.status === 'started' }"
          @click="enterFrom(item)"
        >
          <em>第{{ item.chapters }}回</em>
          <strong>{{ item.title }}</strong>
          <small>{{ item.segment_count }} 段 · {{ item.node_count }} 处抉择</small>
          <i v-if="item.status === 'finished'">已入梦</i>
          <i v-else-if="item.status === 'started'">走到第 {{ item.segment_index + 1 }} 段</i>
        </button>
      </div>
    </div>

    <div v-else class="dream-stage">
      <article ref="scroll" class="dream-text">
        <p class="dream-cast">在场：{{ (segment?.cast ?? []).join('、') }}</p>
        <p v-for="(para, index) in (segment?.text ?? '').split('\n').filter(Boolean)" :key="index">{{ para }}</p>

        <div v-if="segment?.finished" class="dream-exit">
          <p v-if="segment.exit_line">{{ segment.exit_line }}</p>
          <button @click="quit">出梦</button>
        </div>

        <div v-else-if="node" class="dream-node">
          <h3>{{ node.title }}</h3>
          <p class="dream-situation">{{ node.situation }}</p>
          <ol class="dream-options">
            <li v-for="option in node.options" :key="option.key">
              <button
                :disabled="busy || !!picked"
                :class="{ picked: picked === option.key }"
                @click="choose(option.key)"
              >
                <b>{{ option.key }}</b>
                <span>{{ option.text }}</span>
                <q>{{ option.basis }}</q>
              </button>
            </li>
          </ol>
          <p v-if="picked" class="dream-locked">已定。往下走就不能改了——梦里也不该反复涂抹。</p>
        </div>
      </article>

      <aside class="dream-talk">
        <div v-for="line in lines" :key="line.id" class="dream-line" :class="{ self: line.speaker === '我', bad: line.error }">
          <b v-if="line.speaker !== '我'">{{ line.speaker }}<em v-if="line.emotion">{{ line.emotion }}</em></b>
          <p>{{ line.text }}</p>
        </div>
        <p v-if="busy" class="dream-thinking"><i></i>正在斟酌语句……</p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.dream { position: fixed; inset: 0; z-index: 60; display: flex; flex-direction: column; background: linear-gradient(160deg, #1b201c, #141814 60%, #10130f); color: #efe7d6; }
.dream-bar { display: flex; align-items: center; gap: 14px; padding: 12px 22px; border-bottom: 1px solid rgba(229, 206, 164, .22); background: rgba(20, 26, 22, .7); }
.dream-bar .eyebrow { font-size: 10px; letter-spacing: 6px; color: #d3a85b; }
.dream-bar b { font-family: 'Ma Shan Zheng', serif; font-size: 22px; font-weight: 400; letter-spacing: 4px; }
.dream-bar small { font-size: 11px; opacity: .6; }
.dream-bar .ghost { margin-left: auto; padding: 6px 16px; border: 1px solid rgba(229, 206, 164, .45); background: transparent; color: #f1e5cd; cursor: pointer; letter-spacing: 2px; }
.dream-list { flex: 1; overflow-y: auto; padding: 26px 34px 40px; }
.dream-hint { max-width: 720px; margin: 0 0 22px; font-size: 12.5px; line-height: 2; opacity: .72; }
.dream-error { color: #ff9a7a; font-size: 12.5px; }
.dream-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.dream-grid button { position: relative; display: flex; flex-direction: column; gap: 5px; padding: 15px 16px; text-align: left; border: 1px solid rgba(229, 206, 164, .22); background: rgba(32, 40, 34, .55); color: inherit; cursor: pointer; transition: .25s; }
.dream-grid button:hover { border-color: rgba(211, 168, 91, .8); background: rgba(44, 56, 47, .8); transform: translateY(-2px); }
.dream-grid button.done { border-color: rgba(63, 138, 90, .55); }
.dream-grid button.going { border-color: rgba(211, 168, 91, .7); }
.dream-grid em { font-style: normal; font-size: 10px; letter-spacing: 3px; color: #d3a85b; }
.dream-grid strong { font-size: 16px; letter-spacing: 2px; font-weight: 500; }
.dream-grid small { font-size: 10.5px; opacity: .55; }
.dream-grid i { position: absolute; top: 12px; right: 12px; font-style: normal; font-size: 9.5px; opacity: .7; }
.dream-stage { flex: 1; display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, .85fr); overflow: hidden; }
.dream-text { overflow-y: auto; padding: 26px 34px 60px; font-size: 14.5px; line-height: 2.15; border-right: 1px solid rgba(229, 206, 164, .14); }
.dream-text > p { margin: 0 0 14px; text-indent: 2em; }
.dream-cast { text-indent: 0 !important; font-size: 11.5px; letter-spacing: 2px; opacity: .55; }
.dream-node { margin-top: 26px; padding: 18px 20px; border-left: 3px solid #a84536; background: rgba(37, 32, 25, .72); text-indent: 0; }
.dream-node h3 { margin: 0 0 8px; font-size: 15px; letter-spacing: 3px; color: #e5cea4; }
.dream-situation { margin: 0 0 14px; font-size: 13px; line-height: 1.95; opacity: .8; text-indent: 0; }
.dream-options { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.dream-options button { display: grid; grid-template-columns: 22px 1fr; gap: 4px 10px; width: 100%; padding: 11px 13px; text-align: left; border: 1px solid rgba(229, 206, 164, .28); background: rgba(24, 31, 27, .6); color: inherit; cursor: pointer; transition: .2s; }
.dream-options button:hover:not(:disabled) { border-color: #d3a85b; background: rgba(46, 58, 49, .8); }
.dream-options button.picked { border-color: #2fbf71; background: rgba(30, 90, 60, .45); }
.dream-options button:disabled { opacity: .55; cursor: default; }
.dream-options b { grid-row: span 2; font-size: 15px; color: #d3a85b; }
.dream-options span { font-size: 13.5px; }
.dream-options q { grid-column: 2; font-size: 11px; opacity: .5; font-style: normal; }
.dream-locked { margin: 12px 0 0; font-size: 11.5px; color: #8fd3a8; }
.dream-exit { margin-top: 30px; padding: 20px; border: 1px solid rgba(229, 206, 164, .3); background: rgba(30, 36, 30, .7); text-align: center; }
.dream-exit p { margin: 0 0 14px; text-indent: 0; font-size: 15px; letter-spacing: 3px; color: #e5cea4; }
.dream-exit button { padding: 8px 24px; border: 1px solid #a84536; background: #8d3028; color: #f4e6cd; cursor: pointer; letter-spacing: 3px; }
.dream-talk { overflow-y: auto; padding: 26px 24px 60px; display: flex; flex-direction: column; gap: 14px; }
.dream-line b { display: block; font-size: 12px; letter-spacing: 2px; color: #d3a85b; font-weight: 500; }
.dream-line b em { margin-left: 8px; font-style: normal; font-size: 10px; opacity: .6; }
.dream-line p { margin: 5px 0 0; font-size: 14px; line-height: 2; }
.dream-line.self { align-self: flex-end; max-width: 88%; text-align: right; }
.dream-line.self p { padding: 8px 13px; background: rgba(105, 47, 37, .5); border-right: 2px solid #b85a42; }
.dream-line.bad p { padding: 10px 13px; background: rgba(168, 69, 54, .16); border-left: 3px solid #a84536; font-size: 12.5px; }
.dream-thinking { margin: 0; font-size: 12.5px; opacity: .6; }
.dream-thinking i { display: inline-block; width: 6px; height: 6px; margin-right: 8px; border-radius: 50%; background: #d3a85b; animation: dream-pulse 1.1s infinite; }
@keyframes dream-pulse { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
@media (max-width: 1100px) { .dream-stage { grid-template-columns: 1fr; } .dream-talk { border-top: 1px solid rgba(229, 206, 164, .14); } }
</style>
