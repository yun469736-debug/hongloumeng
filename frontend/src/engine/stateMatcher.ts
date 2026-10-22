import type { Character, CharacterState, DialogueSentenceEvent, TransitionPreset } from '../types'

const synonyms: Record<string, string[]> = {
  开心: ['欢喜', '欣然', '浅笑', '爽朗', '畅快'],
  欢喜: ['开心', '欣然', '浅笑', '爽朗'],
  伤心: ['哀愁', '伤感', '伤怀', '落泪', '委屈'],
  委屈: ['伤心', '哀愁', '含泪', '忧郁'],
  忧郁: ['惆怅', '伤感', '含愁', '沉思'],
  生气: ['不悦', '嗔怒', '恼怒', '严肃'],
  惊讶: ['意外', '微讶', '警觉', '一怔'],
  温柔: ['温和', '温婉', '亲切', '柔情'],
  平静: ['沉静', '端静', '从容', '淡然'],
  自信: ['坚定', '果断', '英气', '豪迈'],
  低眉: ['垂眸', '垂首', '低首'],
  回眸: ['回望', '侧眸', '侧望'],
  含笑: ['浅笑', '展颜'],
  阅卷: ['静读', '阅读'],
  正视: ['凝望', '审视'],
}

function relatedTerms(term: string): Set<string> {
  return new Set([term, ...(synonyms[term] ?? [])])
}

function tagScore(target: string, candidates: string[], weight: number): number {
  if (!target) return 0
  const related = relatedTerms(target)
  let best = 0
  for (const candidate of candidates) {
    if (candidate === target) best = Math.max(best, weight)
    else if (candidate.includes(target) || target.includes(candidate)) best = Math.max(best, weight * .82)
    else if (related.has(candidate) || relatedTerms(candidate).has(target)) best = Math.max(best, weight * .68)
  }
  return best
}

export function matchCharacterState(
  character: Character,
  target: Pick<DialogueSentenceEvent, 'emotion' | 'action' | 'intensity'>,
  currentStateId?: string,
): CharacterState {
  return character.states
    .map(state => {
      const emotion = tagScore(target.emotion, state.emotions, 6)
      const action = tagScore(target.action, state.actions, 5)
      const intensity = 2 * (1 - Math.min(1, Math.abs(target.intensity - state.intensity)))
      const freshness = state.id === currentStateId ? -.15 : 0
      return { state, score: emotion + action + intensity + freshness }
    })
    .sort((left, right) => right.score - left.score)[0].state
}

const strongEmotions = new Set(['生气', '恼怒', '嗔怒', '伤心', '落泪', '惊讶', '振奋'])

export function chooseTransition(previous: CharacterState, next: CharacterState): TransitionPreset {
  if (previous.id === next.id) return 'soft'
  const intensityDelta = Math.abs(previous.intensity - next.intensity)
  const strongChange = next.emotions.some(emotion => strongEmotions.has(emotion))
  const actionChanged = previous.actions[0] !== next.actions[0]
  if (intensityDelta >= .4 || (strongChange && actionChanged)) return 'strong'
  if (actionChanged) return 'ink'
  return 'soft'
}
