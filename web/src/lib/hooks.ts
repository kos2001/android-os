import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'

// ------------------------------------------------------------------ 해시 라우터
function currentPath(): string {
  const hash = window.location.hash.replace(/^#/, '')
  return hash || '/overview'
}

function subscribeHash(cb: () => void) {
  window.addEventListener('hashchange', cb)
  return () => window.removeEventListener('hashchange', cb)
}

export function useRoute(): { path: string; segments: string[]; query: URLSearchParams } {
  const full = useSyncExternalStore(subscribeHash, currentPath)
  const [path, search = ''] = full.split('?')
  return { path, segments: path.split('/').filter(Boolean), query: new URLSearchParams(search) }
}

export function navigate(path: string) {
  window.location.hash = path
}

// ------------------------------------------------------------------ 비동기 데이터
export interface AsyncState<T> {
  data: T | undefined
  error: Error | undefined
  loading: boolean
  reload: () => void
}

/** deps 가 바뀌면 다시 불러오고, intervalMs 가 있으면 폴링한다 (탭이 숨겨지면 멈춤). */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], intervalMs?: number): AsyncState<T> {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<Error>()
  const [loading, setLoading] = useState(true)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const seq = useRef(0)

  const load = useCallback((quiet = false) => {
    const id = ++seq.current
    if (!quiet) setLoading(true)
    fnRef.current()
      .then((d) => {
        if (id === seq.current) {
          setData(d)
          setError(undefined)
        }
      })
      .catch((e: Error) => id === seq.current && setError(e))
      .finally(() => id === seq.current && setLoading(false))
  }, [])

  useEffect(() => {
    load()
    if (!intervalMs) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') load(true)
    }, intervalMs)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error, loading, reload: () => load(true) }
}

// ------------------------------------------------------------------ 테마
export type ThemeChoice = 'system' | 'light' | 'dark'

function applyTheme(choice: ThemeChoice) {
  const dark = choice === 'dark' || (choice === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
}

export function useTheme(): [ThemeChoice, (t: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() => {
    try {
      return (localStorage.getItem('theme') as ThemeChoice) || 'system'
    } catch {
      return 'system'
    }
  })
  useEffect(() => {
    applyTheme(choice)
    try {
      localStorage.setItem('theme', choice)
    } catch {
      /* 저장 불가 */
    }
    if (choice !== 'system') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => applyTheme('system')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [choice])
  return [choice, setChoice]
}

export function useHotkey(key: string, handler: (e: KeyboardEvent) => void, meta = false) {
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== key.toLowerCase()) return
      if (meta && !(e.metaKey || e.ctrlKey)) return
      if (!meta && (e.metaKey || e.ctrlKey || e.altKey)) return
      const target = e.target as HTMLElement
      if (!meta && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return
      ref.current(e)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [key, meta])
}
