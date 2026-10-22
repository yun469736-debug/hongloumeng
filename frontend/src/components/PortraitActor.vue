<script setup lang="ts">
import { computed } from 'vue'
import type { ActorVisual, Character } from '../types'

const props = defineProps<{
  character: Character
  visual: ActorVisual
  speaking: boolean
  loading: boolean
  removable: boolean
}>()

defineEmits<{
  activate: []
  remove: []
}>()

const transitionName = computed(() => `portrait-${props.visual.transition}`)
const alignmentStyle = computed(() => ({
  '--portrait-scale': String(props.visual.state.alignment.scale),
  '--portrait-x': `${props.visual.state.alignment.offsetX}%`,
  '--portrait-y': `${props.visual.state.alignment.offsetY}%`,
}))
</script>

<template>
  <article
    class="portrait"
    :class="{ speaking, loading }"
    :aria-label="`${character.name}，当前状态：${visual.state.label}`"
    @click="$emit('activate')"
  >
    <div class="portrait-frame">
      <Transition :name="transitionName">
        <div
          :key="`${visual.state.id}-${visual.revision}`"
          class="portrait-layer"
          :class="`motion-${visual.state.motion}`"
          :style="alignmentStyle"
        >
          <img :src="visual.state.image" :alt="`${character.name}·${visual.state.label}`">
        </div>
      </Transition>
      <span v-if="loading" class="portrait-loading">立绘载入中</span>
      <button v-if="removable" class="remove" :aria-label="`请${character.name}离席`" @click.stop="$emit('remove')">×</button>
    </div>
    <div class="nameplate">
      <strong>{{ character.name }}</strong>
      <span>{{ character.courtesy }} · {{ visual.state.label }}</span>
    </div>
  </article>
</template>
