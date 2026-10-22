<script setup lang="ts">
import { computed, ref } from 'vue'
import { scenes } from '../data'

/** 退出校准：回到普通的贾府全图 */
function exit() {
  const url = new URL(window.location.href)
  url.searchParams.delete('calibrate')
  window.location.href = url.toString()
}

/**
 * 吸附锚点：由像素分析从 贾府.png（1448×1086）里检出的墨色文字块中心。
 * A1–A14 是同位同字号的干净标签（高可信），A15 起尺寸不一，可能混着插画元素。
 */
const ANCHORS: { id: string; x: number; y: number; strong: boolean }[] = [
  { id: 'A1', x: 25.87, y: 12.34, strong: true },
  { id: 'A2', x: 73.72, y: 13.21, strong: true },
  { id: 'A3', x: 88.26, y: 25.97, strong: true },
  { id: 'A4', x: 15.61, y: 30.89, strong: true },
  { id: 'A5', x: 51.69, y: 32.14, strong: true },
  { id: 'A6', x: 71.17, y: 34.35, strong: true },
  { id: 'A7', x: 15.88, y: 55.75, strong: true },
  { id: 'A8', x: 28.83, y: 60.08, strong: true },
  { id: 'A9', x: 15.64, y: 67.82, strong: true },
  { id: 'A10', x: 28.31, y: 79.56, strong: true },
  { id: 'A11', x: 75.0, y: 79.6, strong: true },
  { id: 'A12', x: 50.14, y: 90.01, strong: true },
  { id: 'A13', x: 49.69, y: 9.71, strong: true },
  { id: 'A14', x: 83.25, y: 90.1, strong: true },
  { id: 'A15', x: 94.65, y: 7.92, strong: false },
  { id: 'A16', x: 85.53, y: 17.45, strong: false },
  { id: 'A17', x: 77.94, y: 82.5, strong: false },
  { id: 'A18', x: 24.97, y: 82.74, strong: false },
  { id: 'A19', x: 71.24, y: 82.92, strong: false },
  { id: 'A20', x: 31.32, y: 82.5, strong: false },
  { id: 'A21', x: 24.31, y: 20.35, strong: false },
  { id: 'A22', x: 49.41, y: 67.5, strong: false },
]

const SNAP = 2.6 // 吸附半径（百分点）

type Mark = { x: number; y: number; anchor: string }

const canvas = ref<HTMLElement>()
const hover = ref<{ x: number; y: number } | null>(null)
const cursor = ref(0)
const snapNote = ref('')
const copied = ref(false)

/** 已标定的坐标；未标定的沿用 data.ts 旧值，好让你看出偏差有多大 */
const picked = ref<Record<string, Mark | null>>(
  Object.fromEntries(scenes.map(scene => [scene.id, null])),
)

const doneCount = computed(() => Object.values(picked.value).filter(Boolean).length)
const currentScene = computed(() => scenes[cursor.value])

function nearestAnchor(x: number, y: number) {
  let best: { id: string; x: number; y: number; d: number } | null = null
  for (const anchor of ANCHORS) {
    const d = Math.hypot(anchor.x - x, anchor.y - y)
    if (d <= SNAP && (!best || d < best.d)) best = { id: anchor.id, x: anchor.x, y: anchor.y, d }
  }
  return best
}

function toPercent(event: MouseEvent) {
  const box = canvas.value?.getBoundingClientRect()
  if (!box) return null
  return {
    x: ((event.clientX - box.left) / box.width) * 100,
    y: ((event.clientY - box.top) / box.height) * 100,
  }
}

function onMove(event: MouseEvent) {
  hover.value = toPercent(event)
}

function pick(event: MouseEvent) {
  const raw = toPercent(event)
  if (!raw) return
  const anchor = nearestAnchor(raw.x, raw.y)
  const x = anchor ? anchor.x : raw.x
  const y = anchor ? anchor.y : raw.y
  const where = x.toFixed(1) + ', ' + y.toFixed(1)
  picked.value = {
    ...picked.value,
    [currentScene.value.id]: { x: Number(x.toFixed(2)), y: Number(y.toFixed(2)), anchor: anchor ? anchor.id : '' },
  }
  snapNote.value = anchor ? '已吸附到 ' + anchor.id + '（' + where + '）' : '自由落点（' + where + '）'
  if (cursor.value < scenes.length - 1) cursor.value += 1
}

function clearOne(id: string) {
  picked.value = { ...picked.value, [id]: null }
}

function resetAll() {
  picked.value = Object.fromEntries(scenes.map(scene => [scene.id, null]))
  cursor.value = 0
  snapNote.value = ''
}

const fullSnippet = computed(() => {
  const body = scenes
    .map(scene => {
      const mark = picked.value[scene.id]
      const x = mark ? mark.x : scene.hotspot[0]
      const y = mark ? mark.y : scene.hotspot[1]
      return '  ' + scene.id + ': [' + x + ', ' + y + '], // ' + scene.name
    })
    .join('\n')
  return 'const hotspots: Record<string, [number, number]> = {\n' + body + '\n}'
})

async function copyCode() {
  try {
    await navigator.clipboard.writeText(fullSnippet.value)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 2500)
  } catch {
    copied.value = false
  }
}
</script>

<template>
  <div class="calib">
    <div class="calib-bar">
      <b>地图热区校准</b>
      <span>依次点击图上画好的房间名；靠近白点会自动吸附，保证热区正压在字上</span>
      <em>{{ doneCount }} / {{ scenes.length }}</em>
      <button @click="resetAll">全部重来</button>
      <button class="ghost" @click="copyCode">{{ copied ? '已复制' : '复制坐标代码' }}</button>
      <button class="ghost" @click="exit">退出校准</button>
    </div>

    <div class="calib-stage">
      <div ref="canvas" class="calib-canvas" @mousemove="onMove" @mouseleave="hover = null" @click="pick">
        <img src="/assets/buildings/贾府.png" alt="贾府全图">
        <span
          v-for="anchor in ANCHORS"
          :key="anchor.id"
          class="calib-anchor"
          :class="{ strong: anchor.strong }"
          :style="{ left: anchor.x + '%', top: anchor.y + '%' }"
          :title="anchor.id"
        ></span>
        <span
          v-for="scene in scenes"
          :key="scene.id"
          class="calib-box"
          :class="{ done: picked[scene.id], current: scene.id === currentScene.id }"
          :style="{ left: (picked[scene.id]?.x ?? scene.hotspot[0]) + '%', top: (picked[scene.id]?.y ?? scene.hotspot[1]) + '%' }"
        >{{ scene.name }}</span>
        <span v-if="hover" class="calib-cross" :style="{ left: hover.x + '%', top: hover.y + '%' }"></span>
      </div>
    </div>

    <div class="calib-foot">
      <p v-if="hover" class="readout">{{ hover.x.toFixed(1) }} , {{ hover.y.toFixed(1) }}</p>
      <p class="target">当前标注：<b>{{ currentScene.name }}</b>（{{ currentScene.subtitle }}）</p>
      <p v-if="snapNote" class="snap">{{ snapNote }}</p>
      <ul class="calib-list">
        <li v-for="(scene, index) in scenes" :key="scene.id" :class="{ done: !!picked[scene.id], current: index === cursor }">
          <button @click="cursor = index">{{ scene.name }}</button>
          <small v-if="picked[scene.id]">{{ picked[scene.id]!.x }} , {{ picked[scene.id]!.y }}<i v-if="picked[scene.id]!.anchor"> &larr;{{ picked[scene.id]!.anchor }}</i></small>
          <small v-else class="old">旧值 {{ scene.hotspot[0] }} , {{ scene.hotspot[1] }}</small>
          <button v-if="picked[scene.id]" class="x" @click="clearOne(scene.id)">&times;</button>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.calib { position: fixed; inset: 0; z-index: 90; display: flex; flex-direction: column; background: #171c18; color: #efe7d6; }
.calib-bar { display: flex; align-items: center; gap: 14px; padding: 10px 18px; background: #232b25; border-bottom: 1px solid rgba(229, 206, 164, .22); font-size: 12px; }
.calib-bar b { letter-spacing: 2px; color: #e5cea4; }
.calib-bar span { opacity: .6; }
.calib-bar em { margin-left: auto; font-style: normal; color: #d3a85b; }
.calib-bar button { padding: 5px 12px; border: 1px solid rgba(229, 206, 164, .4); background: rgba(105, 47, 37, .7); color: #f1e5cd; cursor: pointer; font-size: 12px; }
.calib-bar button.ghost { background: transparent; }
.calib-stage { flex: 1; display: flex; justify-content: center; overflow: hidden; background: #d9ccb0; }
.calib-canvas { position: relative; height: 100%; aspect-ratio: 1448 / 1086; flex: none; cursor: crosshair; }
.calib-canvas > img { width: 100%; height: 100%; display: block; }
.calib-anchor { position: absolute; width: 5px; height: 5px; margin: -2.5px 0 0 -2.5px; border-radius: 50%; background: rgba(255, 255, 255, .85); box-shadow: 0 0 0 1px rgba(0, 0, 0, .5); pointer-events: none; }
.calib-anchor.strong { width: 7px; height: 7px; margin: -3.5px 0 0 -3.5px; background: #fff; }
.calib-box { position: absolute; width: 130px; height: 48px; transform: translate(-50%, -50%); display: flex; align-items: center; justify-content: center; font-size: 11px; letter-spacing: 1px; color: #fff; background: rgba(0, 80, 255, .38); border: 1px solid rgba(0, 80, 255, .85); pointer-events: none; }
.calib-box.done { background: rgba(30, 130, 70, .42); border-color: #2fbf71; }
.calib-box.current { background: rgba(200, 60, 40, .5); border-color: #ff6b4a; box-shadow: 0 0 0 3px rgba(255, 200, 150, .35); }
.calib-cross { position: absolute; width: 22px; height: 22px; margin: -11px 0 0 -11px; border: 1px dashed rgba(255, 255, 255, .9); border-radius: 50%; pointer-events: none; }
.calib-foot { display: flex; align-items: flex-start; gap: 20px; padding: 10px 18px; background: #232b25; border-top: 1px solid rgba(229, 206, 164, .22); font-size: 12px; max-height: 30vh; overflow-y: auto; }
.readout { margin: 0; min-width: 110px; font-family: ui-monospace, monospace; color: #d3a85b; }
.target { margin: 0; min-width: 190px; }
.snap { margin: 0; color: #8fd3a8; min-width: 220px; }
.calib-list { display: flex; flex-wrap: wrap; gap: 4px 8px; margin: 0; padding: 0; list-style: none; }
.calib-list li { display: flex; align-items: center; gap: 5px; padding: 2px 7px; border: 1px solid rgba(229, 206, 164, .2); }
.calib-list li.current { border-color: #ff6b4a; }
.calib-list li.done { border-color: rgba(47, 191, 113, .6); }
.calib-list button { border: 0; background: transparent; color: #efe7d6; cursor: pointer; font-size: 12px; padding: 0; }
.calib-list small { opacity: .7; font-size: 10px; font-family: ui-monospace, monospace; }
.calib-list small.old { opacity: .35; }
.calib-list button.x { color: #ff8b6a; padding: 0 2px; }
</style>
