// 한국어·영어 UI. 문구는 호출 위치에 두 언어를 나란히 적는다: t('판정 실행', 'Run check')
// 언어는 사용자가 고른 값(localStorage) → 브라우저 언어(ko* 이면 한국어, 아니면 영어) 순으로 정한다.
import { useCallback, useSyncExternalStore } from 'react'

export type Lang = 'ko' | 'en'

const STORAGE_KEY = 'lang'
const listeners = new Set<() => void>()

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'ko' || saved === 'en') return saved
  } catch {
    // 저장소 접근이 막힌 환경 — 브라우저 언어로 결정
  }
  return navigator.language?.toLowerCase().startsWith('ko') ? 'ko' : 'en'
}

let current: Lang = initialLang()
document.documentElement.lang = current

export function getLang(): Lang {
  return current
}

export function setLang(lang: Lang) {
  if (lang === current) return
  current = lang
  document.documentElement.lang = lang
  try {
    localStorage.setItem(STORAGE_KEY, lang)
  } catch {
    // 저장 실패 시 이번 세션에만 적용
  }
  listeners.forEach((l) => l())
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

/** 컴포넌트 밖(포맷 함수 등)에서 쓰는 번역. 렌더 중 호출하면 현재 언어를 따른다. */
export function tr(ko: string, en: string): string {
  return current === 'ko' ? ko : en
}

export function useLang(): [Lang, (lang: Lang) => void] {
  return [useSyncExternalStore(subscribe, getLang), setLang]
}

/** 언어가 바뀌면 다시 렌더되는 번역 함수. */
export function useT(): (ko: string, en: string) => string {
  const [lang] = useLang()
  return useCallback((ko: string, en: string) => (lang === 'ko' ? ko : en), [lang])
}

export function locale(): string {
  return current === 'ko' ? 'ko-KR' : 'en-US'
}

/** 서버 finding 은 title/detail(한국어)와 title_en/detail_en 을 준다. 영어가 없으면(이전 판정) 한국어. */
export function localized<T extends { title: string; detail: string; title_en?: string | null; detail_en?: string | null }>(
  f: T, lang: Lang,
): { title: string; detail: string } {
  if (lang === 'en' && f.title_en) return { title: f.title_en, detail: f.detail_en || f.detail }
  return { title: f.title, detail: f.detail }
}

/** { key: [ko, en] } → 읽을 때마다 현재 언어 문자열을 돌려주는 레코드 (LABEL[key] 호출부를 그대로 둔다). */
export function localizedRecord<K extends string>(pairs: Record<K, [string, string]>): Record<K, string> {
  const out = {} as Record<K, string>
  for (const key of Object.keys(pairs) as K[]) {
    Object.defineProperty(out, key, { enumerable: true, get: () => tr(pairs[key][0], pairs[key][1]) })
  }
  return out
}
