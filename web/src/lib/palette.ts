// 공통 색 계열. 각 계열은 라이트(50 배경 + 700/800 글자)와 다크(500/10 배경 + 300 글자) 조합으로 본문 대비를 유지한다.
// 장식용 색이다 — 상태(성공·경고·위험)는 status.tsx 의 톤을 쓰고, 색만으로 뜻을 전하지 않도록 아이콘·라벨을 함께 둔다.
import { useRoute } from './hooks'

export type Hue = 'sky' | 'blue' | 'indigo' | 'violet' | 'purple' | 'fuchsia' | 'pink' | 'rose' | 'orange' | 'amber'
  | 'yellow' | 'lime' | 'emerald' | 'teal' | 'cyan' | 'slate'

export interface HueClasses {
  soft: string // 옅은 배경
  text: string // 글자·아이콘
  ring: string // 테두리(ring)
  solid: string // 채운 배경 (흰 글자)
  bar: string // 그라디언트 from/to
  dot: string // 작은 점·막대
  border: string // 왼쪽/위 강조선
}

// Tailwind 는 소스에 적힌 완전한 클래스 문자열만 생성하므로 조합하지 않고 그대로 적는다.
export const HUE: Record<Hue, HueClasses> = {
  sky: {
    soft: 'bg-sky-50 dark:bg-sky-500/10', text: 'text-sky-700 dark:text-sky-300', ring: 'ring-sky-200 dark:ring-sky-500/30',
    solid: 'bg-sky-600', bar: 'from-sky-400 to-sky-600', dot: 'bg-sky-500', border: 'border-sky-400 dark:border-sky-500/60',
  },
  blue: {
    soft: 'bg-blue-50 dark:bg-blue-500/10', text: 'text-blue-700 dark:text-blue-300', ring: 'ring-blue-200 dark:ring-blue-500/30',
    solid: 'bg-blue-600', bar: 'from-blue-400 to-blue-600', dot: 'bg-blue-500', border: 'border-blue-400 dark:border-blue-500/60',
  },
  indigo: {
    soft: 'bg-indigo-50 dark:bg-indigo-500/10', text: 'text-indigo-700 dark:text-indigo-300', ring: 'ring-indigo-200 dark:ring-indigo-500/30',
    solid: 'bg-indigo-600', bar: 'from-indigo-400 to-indigo-600', dot: 'bg-indigo-500', border: 'border-indigo-400 dark:border-indigo-500/60',
  },
  violet: {
    soft: 'bg-violet-50 dark:bg-violet-500/10', text: 'text-violet-700 dark:text-violet-300', ring: 'ring-violet-200 dark:ring-violet-500/30',
    solid: 'bg-violet-600', bar: 'from-violet-400 to-violet-600', dot: 'bg-violet-500', border: 'border-violet-400 dark:border-violet-500/60',
  },
  purple: {
    soft: 'bg-purple-50 dark:bg-purple-500/10', text: 'text-purple-700 dark:text-purple-300', ring: 'ring-purple-200 dark:ring-purple-500/30',
    solid: 'bg-purple-600', bar: 'from-purple-400 to-purple-600', dot: 'bg-purple-500', border: 'border-purple-400 dark:border-purple-500/60',
  },
  fuchsia: {
    soft: 'bg-fuchsia-50 dark:bg-fuchsia-500/10', text: 'text-fuchsia-700 dark:text-fuchsia-300', ring: 'ring-fuchsia-200 dark:ring-fuchsia-500/30',
    solid: 'bg-fuchsia-600', bar: 'from-fuchsia-400 to-fuchsia-600', dot: 'bg-fuchsia-500', border: 'border-fuchsia-400 dark:border-fuchsia-500/60',
  },
  pink: {
    soft: 'bg-pink-50 dark:bg-pink-500/10', text: 'text-pink-700 dark:text-pink-300', ring: 'ring-pink-200 dark:ring-pink-500/30',
    solid: 'bg-pink-600', bar: 'from-pink-400 to-pink-600', dot: 'bg-pink-500', border: 'border-pink-400 dark:border-pink-500/60',
  },
  rose: {
    soft: 'bg-rose-50 dark:bg-rose-500/10', text: 'text-rose-700 dark:text-rose-300', ring: 'ring-rose-200 dark:ring-rose-500/30',
    solid: 'bg-rose-600', bar: 'from-rose-400 to-rose-600', dot: 'bg-rose-500', border: 'border-rose-400 dark:border-rose-500/60',
  },
  orange: {
    soft: 'bg-orange-50 dark:bg-orange-500/10', text: 'text-orange-700 dark:text-orange-300', ring: 'ring-orange-200 dark:ring-orange-500/30',
    solid: 'bg-orange-600', bar: 'from-orange-400 to-orange-600', dot: 'bg-orange-500', border: 'border-orange-400 dark:border-orange-500/60',
  },
  amber: {
    soft: 'bg-amber-50 dark:bg-amber-500/10', text: 'text-amber-800 dark:text-amber-300', ring: 'ring-amber-200 dark:ring-amber-500/30',
    solid: 'bg-amber-600', bar: 'from-amber-400 to-amber-600', dot: 'bg-amber-500', border: 'border-amber-400 dark:border-amber-500/60',
  },
  yellow: {
    soft: 'bg-yellow-50 dark:bg-yellow-500/10', text: 'text-yellow-800 dark:text-yellow-300', ring: 'ring-yellow-200 dark:ring-yellow-500/30',
    solid: 'bg-yellow-600', bar: 'from-yellow-400 to-yellow-600', dot: 'bg-yellow-500', border: 'border-yellow-400 dark:border-yellow-500/60',
  },
  lime: {
    soft: 'bg-lime-50 dark:bg-lime-500/10', text: 'text-lime-800 dark:text-lime-300', ring: 'ring-lime-200 dark:ring-lime-500/30',
    solid: 'bg-lime-600', bar: 'from-lime-400 to-lime-600', dot: 'bg-lime-500', border: 'border-lime-400 dark:border-lime-500/60',
  },
  emerald: {
    soft: 'bg-emerald-50 dark:bg-emerald-500/10', text: 'text-emerald-700 dark:text-emerald-300', ring: 'ring-emerald-200 dark:ring-emerald-500/30',
    solid: 'bg-emerald-600', bar: 'from-emerald-400 to-emerald-600', dot: 'bg-emerald-500', border: 'border-emerald-400 dark:border-emerald-500/60',
  },
  teal: {
    soft: 'bg-teal-50 dark:bg-teal-500/10', text: 'text-teal-700 dark:text-teal-300', ring: 'ring-teal-200 dark:ring-teal-500/30',
    solid: 'bg-teal-600', bar: 'from-teal-400 to-teal-600', dot: 'bg-teal-500', border: 'border-teal-400 dark:border-teal-500/60',
  },
  cyan: {
    soft: 'bg-cyan-50 dark:bg-cyan-500/10', text: 'text-cyan-700 dark:text-cyan-300', ring: 'ring-cyan-200 dark:ring-cyan-500/30',
    solid: 'bg-cyan-600', bar: 'from-cyan-400 to-cyan-600', dot: 'bg-cyan-500', border: 'border-cyan-400 dark:border-cyan-500/60',
  },
  slate: {
    soft: 'bg-slate-50 dark:bg-slate-500/10', text: 'text-slate-700 dark:text-slate-300', ring: 'ring-slate-200 dark:ring-slate-500/30',
    solid: 'bg-slate-600', bar: 'from-slate-400 to-slate-600', dot: 'bg-slate-500', border: 'border-slate-400 dark:border-slate-500/60',
  },
}

export const HUES = Object.keys(HUE) as Hue[]

// 페이지(첫 경로 세그먼트)별 대표 색
export const PAGE_HUE: Record<string, Hue> = {
  about: 'violet', overview: 'sky', platforms: 'indigo', knowledge: 'teal', vintf: 'fuchsia',
  packages: 'emerald', rollouts: 'orange', delta: 'cyan', audit: 'slate', settings: 'rose',
}

export function usePageHue(): Hue {
  const { segments } = useRoute()
  return PAGE_HUE[segments[0] ?? 'overview'] ?? 'sky'
}

// 자동 배정에는 상태색과 헷갈리는 계열(rose·pink = 위험, orange·amber·yellow = 경고, emerald·lime = 성공)을 쓰지 않는다
const HASH_HUES: Hue[] = ['sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'teal', 'cyan']

/** 문자열(채널·릴리스·이름)에 항상 같은 색을 준다. */
export function hueOf(key: string): Hue {
  let h = 0
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0
  return HASH_HUES[h % HASH_HUES.length]
}
