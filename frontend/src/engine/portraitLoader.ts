const portraitCache = new Map<string, Promise<void>>()

export function preloadPortrait(source: string): Promise<void> {
  const cached = portraitCache.get(source)
  if (cached) return cached

  const pending = new Promise<void>((resolve, reject) => {
    const image = new Image()
    image.onload = () => {
      if (typeof image.decode !== 'function') resolve()
      else image.decode().then(resolve).catch(resolve)
    }
    image.onerror = () => reject(new Error(`立绘加载失败：${source}`))
    image.src = source
  })
  portraitCache.set(source, pending)
  return pending
}

export async function preloadCharacter(sources: string[]): Promise<void> {
  await Promise.allSettled(sources.map(preloadPortrait))
}
