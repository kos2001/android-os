import { getLang, locale, tr } from './i18n'

const rtfCache = new Map<string, Intl.RelativeTimeFormat>()
function rtf(): Intl.RelativeTimeFormat {
  const lang = getLang()
  let f = rtfCache.get(lang)
  if (!f) rtfCache.set(lang, (f = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })))
  return f
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  const abs = Math.abs(diff)
  if (abs < 45) return tr('방금', 'just now')
  if (abs < 3600) return rtf().format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf().format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 30) return rtf().format(Math.round(diff / 86400), 'day')
  return dateTime(iso)
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(locale(), {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

export function num(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString(locale())
}

export function pct(n: number | null | undefined, digits = 1): string {
  return n == null || Number.isNaN(n) ? '—' : `${(n * 100).toFixed(digits)}%`
}

/** google/lynx/lynx:17/CP2A.260705.006/15641320:user/release-keys → 구성 요소 */
export function parseFingerprint(fp: string) {
  const m = fp.match(/^([^/]+)\/([^/]+)\/([^:]+):([^/]+)\/([^/]+)\/([^:]+):([^/]+)\/(.+)$/)
  if (!m) return { brand: '', product: '', device: '', release: '', buildId: fp, incremental: '', type: '', tags: '' }
  const [, brand, product, device, release, buildId, incremental, type, tags] = m
  return { brand, product, device, release, buildId, incremental, type, tags }
}

export function shortFingerprint(fp: string): string {
  const f = parseFingerprint(fp)
  return f.release ? `${f.device} · Android ${f.release} · ${f.buildId}` : fp
}
