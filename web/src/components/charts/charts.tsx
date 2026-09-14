import { Table2, TrendingUp } from 'lucide-react'
import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { num } from '../../lib/format'
import { Button, cx } from '../ui/primitives'

// 차트 규칙 (dataviz): 선 2px · 마커 r≥4 + 표면색 2px 링 · 막대 ≤24px, 데이터 끝 4px 라운드 · 헤어라인 그리드 ·
// 2개 이상 시리즈는 범례 + 끝 직접 라벨 · 텍스트는 잉크 토큰 · 호버 툴팁 · 표 보기 제공

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(el)
    setWidth(el.getBoundingClientRect().width)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

function niceMax(v: number): number {
  if (v <= 4) return 4
  const pow = 10 ** Math.floor(Math.log10(v))
  const step = [1, 2, 2.5, 5, 10].find((s) => s * pow * 4 >= v) ?? 10
  return step * pow * 4
}

export interface Series {
  key: string
  label: string
  color: string // CSS 변수 (var(--series-n))
}

function Legend({ series }: { series: Series[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded-full" style={{ background: s.color }} />
          {s.label}
        </li>
      ))}
    </ul>
  )
}

function ChartFrame({ title, subtitle, legend, table, children }: {
  title: ReactNode; subtitle?: ReactNode; legend?: ReactNode; table: ReactNode; children: ReactNode
}) {
  const [asTable, setAsTable] = useState(false)
  return (
    <figure className="min-w-0">
      <figcaption className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-semibold text-ink">{title}</p>
          {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-3">
          {legend}
          <Button size="sm" variant="ghost" onClick={() => setAsTable(!asTable)}
            icon={asTable ? <TrendingUp className="size-3.5" /> : <Table2 className="size-3.5" />}
            aria-label={asTable ? '차트로 보기' : '표로 보기'}>
            {asTable ? '차트' : '표'}
          </Button>
        </div>
      </figcaption>
      {asTable ? <div className="scrollbar-thin max-h-72 overflow-auto rounded-md border border-line">{table}</div> : children}
    </figure>
  )
}

// ------------------------------------------------------------------ 시계열 선 차트
export function LineChart<T extends object>({ data, x, series, title, subtitle, height = 220,
  formatX }: {
  data: T[]; x: keyof T & string; series: Series[]; title: ReactNode; subtitle?: ReactNode; height?: number
  formatX: (v: string) => string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const pad = { top: 12, right: 88, bottom: 24, left: 36 }
  const innerW = Math.max(width - pad.left - pad.right, 10)
  const innerH = height - pad.top - pad.bottom
  const max = niceMax(Math.max(1, ...data.flatMap((d) => series.map((s) => Number((d as Record<string, unknown>)[s.key]) || 0))))
  const xAt = (i: number) => pad.left + (data.length <= 1 ? innerW / 2 : (i / (data.length - 1)) * innerW)
  const yAt = (v: number) => pad.top + innerH - (v / max) * innerH
  const ticks = [0, max / 4, max / 2, (3 * max) / 4, max]
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(innerW / 70))))

  const paths = useMemo(() => series.map((s) =>
    data.map((d, i) => `${i ? 'L' : 'M'}${xAt(i).toFixed(1)},${yAt(Number((d as Record<string, unknown>)[s.key]) || 0).toFixed(1)}`).join('')),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [data, series, width, height, max])

  // 끝 라벨 충돌 시 쌓지 않고 범례·툴팁에 맡긴다
  const last = data.length - 1
  const endY = series.map((s) => (last >= 0 ? yAt(Number((data[last] as Record<string, unknown>)[s.key]) || 0) : 0))
  const collide = endY.some((y, i) => endY.some((y2, j) => i !== j && Math.abs(y - y2) < 16))

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left - pad.left
    const i = Math.round((px / innerW) * (data.length - 1))
    setHover(i >= 0 && i < data.length ? i : null)
  }

  const table = (
    <table className="w-full text-xs">
      <thead className="sticky top-0 bg-surface"><tr className="border-b border-line text-muted">
        <th className="px-3 py-2 text-left font-medium">시간</th>
        {series.map((s) => <th key={s.key} className="px-3 py-2 text-right font-medium">{s.label}</th>)}
      </tr></thead>
      <tbody>{data.map((d, i) => (
        <tr key={i} className="border-b border-line last:border-0">
          <td className="px-3 py-1.5 text-ink-2">{formatX(String((d as Record<string, unknown>)[x]))}</td>
          {series.map((s) => <td key={s.key} className="tabular px-3 py-1.5 text-right">{num(Number((d as Record<string, unknown>)[s.key]))}</td>)}
        </tr>
      ))}</tbody>
    </table>
  )

  return (
    <ChartFrame title={title} subtitle={subtitle} legend={<Legend series={series} />} table={table}>
      <div ref={ref} className="relative" style={{ height }}>
        {width > 0 && (
          <svg width={width} height={height} className="block touch-none" onPointerMove={onMove}
            onPointerLeave={() => setHover(null)} role="img" aria-label={typeof title === 'string' ? title : undefined}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={pad.left} x2={pad.left + innerW} y1={yAt(t)} y2={yAt(t)} stroke="var(--grid)" strokeWidth={1} />
                <text x={pad.left - 8} y={yAt(t)} dy="0.32em" textAnchor="end" className="tabular fill-muted text-[10px]">
                  {num(Math.round(t))}
                </text>
              </g>
            ))}
            <line x1={pad.left} x2={pad.left + innerW} y1={yAt(0)} y2={yAt(0)} stroke="var(--axis)" strokeWidth={1} />
            {data.map((d, i) => i % labelEvery === 0 && (
              <text key={i} x={xAt(i)} y={height - 6} textAnchor="middle" className="fill-muted text-[10px]">
                {formatX(String((d as Record<string, unknown>)[x]))}
              </text>
            ))}
            {hover != null && (
              <line x1={xAt(hover)} x2={xAt(hover)} y1={pad.top} y2={pad.top + innerH} stroke="var(--axis)" strokeWidth={1} />
            )}
            {series.map((s, si) => (
              <g key={s.key}>
                <path d={paths[si]} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {last >= 0 && (
                  <>
                    <circle cx={xAt(last)} cy={endY[si]} r={4} fill={s.color} stroke="rgb(var(--surface))" strokeWidth={2} />
                    {!collide && (
                      <text x={xAt(last) + 8} y={endY[si]} dy="0.32em" className="fill-ink-2 text-[11px]">
                        {s.label} <tspan className="tabular fill-ink font-semibold">{num(Number((data[last] as Record<string, unknown>)[s.key]))}</tspan>
                      </text>
                    )}
                  </>
                )}
                {hover != null && (
                  <circle cx={xAt(hover)} cy={yAt(Number((data[hover] as Record<string, unknown>)[s.key]) || 0)} r={4} fill={s.color}
                    stroke="rgb(var(--surface))" strokeWidth={2} />
                )}
              </g>
            ))}
          </svg>
        )}
        {hover != null && width > 0 && (
          <div className="pointer-events-none absolute z-10 min-w-36 rounded-md border border-line bg-raised px-2.5 py-2 text-xs shadow-pop"
            style={{ left: Math.min(xAt(hover) + 12, width - 160), top: pad.top }}>
            <p className="mb-1 font-medium text-ink">{formatX(String((data[hover] as Record<string, unknown>)[x]))}</p>
            {series.map((s) => (
              <p key={s.key} className="flex items-center justify-between gap-4 text-ink-2">
                <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 rounded-full" style={{ background: s.color }} />{s.label}</span>
                <span className="tabular font-semibold text-ink">{num(Number((data[hover] as Record<string, unknown>)[s.key]))}</span>
              </p>
            ))}
          </div>
        )}
      </div>
    </ChartFrame>
  )
}

// ------------------------------------------------------------------ 가로 막대 목록 (단일 시리즈)
export function BarList({ items, title, subtitle, valueLabel, empty }: {
  items: { key: string; label: ReactNode; value: number; hint?: string }[]
  title: ReactNode; subtitle?: ReactNode; valueLabel: string; empty?: ReactNode
}) {
  const max = Math.max(1, ...items.map((i) => i.value))
  const [hover, setHover] = useState<string | null>(null)
  const table = (
    <table className="w-full text-xs">
      <thead><tr className="border-b border-line text-muted">
        <th className="px-3 py-2 text-left font-medium">항목</th><th className="px-3 py-2 text-right font-medium">{valueLabel}</th>
      </tr></thead>
      <tbody>{items.map((i) => (
        <tr key={i.key} className="border-b border-line last:border-0">
          <td className="px-3 py-1.5">{i.label}</td><td className="tabular px-3 py-1.5 text-right">{num(i.value)}</td>
        </tr>
      ))}</tbody>
    </table>
  )
  return (
    <ChartFrame title={title} subtitle={subtitle} table={table}>
      {items.length === 0 ? empty : (
        <ul className="space-y-2.5">
          {items.map((i) => (
            <li key={i.key} className="group" onPointerEnter={() => setHover(i.key)} onPointerLeave={() => setHover(null)}>
              <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
                <span className="min-w-0 truncate text-ink-2">{i.label}</span>
                <span className="tabular font-semibold text-ink">{num(i.value)}</span>
              </div>
              <div className="relative h-2.5">
                <div className="h-full rounded-r-[4px] transition-[filter]"
                  style={{ width: `${Math.max((i.value / max) * 100, 1)}%`, background: 'var(--series-1)',
                    filter: hover && hover !== i.key ? 'saturate(0.35) opacity(0.6)' : undefined }} />
                {hover === i.key && i.hint && (
                  <span className="absolute -top-8 left-0 z-10 whitespace-nowrap rounded-md border border-line bg-raised px-2 py-1 text-[11px] text-ink shadow-pop">
                    {i.hint}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </ChartFrame>
  )
}

// ------------------------------------------------------------------ 분할 막대 (전체 대비 구성)
export function SegmentBar({ segments, total }: {
  segments: { key: string; label: string; value: number; color: string; icon?: ReactNode }[]
  total?: number
}) {
  const sum = total ?? segments.reduce((a, s) => a + s.value, 0)
  const [hover, setHover] = useState<string | null>(null)
  return (
    <div>
      <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded-[4px] bg-line/50" role="img"
        aria-label={segments.map((s) => `${s.label} ${s.value}`).join(', ')}>
        {sum > 0 && segments.filter((s) => s.value > 0).map((s) => (
          <div key={s.key} title={`${s.label}: ${num(s.value)}`}
            onPointerEnter={() => setHover(s.key)} onPointerLeave={() => setHover(null)}
            className={cx('h-full transition-opacity', hover && hover !== s.key && 'opacity-40')}
            style={{ width: `${(s.value / sum) * 100}%`, background: s.color }} />
        ))}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center justify-between gap-2 text-xs"
            onPointerEnter={() => setHover(s.key)} onPointerLeave={() => setHover(null)}>
            <span className="flex min-w-0 items-center gap-1.5 text-ink-2">
              <span className="size-2 shrink-0 rounded-sm" style={{ background: s.color }} />
              {s.icon}
              <span className="truncate">{s.label}</span>
            </span>
            <span className="tabular font-semibold text-ink">{num(s.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------------ 기간 막대 (커널 지원 기간)
export function RangeTimeline({ rows, title, subtitle, today }: {
  rows: { key: string; label: string; start: string; end: string; highlight?: boolean }[]
  title: ReactNode; subtitle?: ReactNode; today: Date
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<string | null>(null)
  const starts = rows.map((r) => new Date(r.start).getTime())
  const ends = rows.map((r) => new Date(r.end).getTime())
  const minY = new Date(Math.min(...starts)).getFullYear()
  const maxY = new Date(Math.max(...ends)).getFullYear() + 1
  const t0 = new Date(minY, 0, 1).getTime()
  const t1 = new Date(maxY, 0, 1).getTime()
  const labelW = 120
  const innerW = Math.max(width - labelW - 12, 10)
  const xAt = (t: number) => labelW + ((t - t0) / (t1 - t0)) * innerW
  const rowH = 26
  const top = 16 // '오늘' 라벨 자리
  const height = rows.length * rowH + 22 + top
  const years = Array.from({ length: maxY - minY + 1 }, (_, i) => minY + i)

  const table = (
    <table className="w-full text-xs">
      <thead><tr className="border-b border-line text-muted">
        <th className="px-3 py-2 text-left font-medium">브랜치</th><th className="px-3 py-2 text-left font-medium">출시</th>
        <th className="px-3 py-2 text-left font-medium">EOL</th>
      </tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.key} className="border-b border-line last:border-0">
          <td className="px-3 py-1.5 font-mono">{r.label}</td><td className="px-3 py-1.5">{r.start}</td><td className="px-3 py-1.5">{r.end}</td>
        </tr>
      ))}</tbody>
    </table>
  )

  return (
    <ChartFrame title={title} subtitle={subtitle} table={table}>
      <div ref={ref} className="relative">
        {width > 0 && (
          <svg width={width} height={height} className="block">
            {years.map((y) => (
              <g key={y}>
                <line x1={xAt(new Date(y, 0, 1).getTime())} x2={xAt(new Date(y, 0, 1).getTime())} y1={0} y2={height - 18}
                  stroke="var(--grid)" strokeWidth={1} />
                <text x={xAt(new Date(y, 0, 1).getTime())} y={height - 4} textAnchor="middle" className="tabular fill-muted text-[10px]">{y}</text>
              </g>
            ))}
            {rows.map((r, i) => {
              const y = i * rowH + 5 + top
              const x1 = xAt(new Date(r.start).getTime())
              const x2 = xAt(new Date(r.end).getTime())
              const expired = new Date(r.end) <= today
              return (
                <g key={r.key} onPointerEnter={() => setHover(r.key)} onPointerLeave={() => setHover(null)}>
                  <rect x={0} y={y - 4} width={width} height={rowH} fill="transparent" />
                  <text x={0} y={y + 8} dy="0.32em" className={cx('font-mono text-[11px]', r.highlight ? 'fill-ink font-semibold' : 'fill-ink-2')}>
                    {r.label}
                  </text>
                  <rect x={x1} y={y + 2} width={Math.max(x2 - x1, 2)} height={12} rx={4}
                    fill={expired ? 'var(--axis)' : 'var(--series-1)'}
                    opacity={hover && hover !== r.key ? 0.45 : 1} />
                </g>
              )
            })}
            <line x1={xAt(today.getTime())} x2={xAt(today.getTime())} y1={top - 2} y2={height - 18} stroke="rgb(var(--ink))" strokeWidth={1} />
            <text x={xAt(today.getTime())} y={9} textAnchor="middle" className="fill-ink text-[10px] font-semibold">오늘</text>
          </svg>
        )}
        {hover && (() => {
          const r = rows.find((row) => row.key === hover)!
          const i = rows.indexOf(r)
          return (
            <div className="pointer-events-none absolute z-10 rounded-md border border-line bg-raised px-2.5 py-1.5 text-xs shadow-pop"
              style={{ left: Math.min(xAt(new Date(r.end).getTime()) + 8, width - 180), top: i * rowH - 2 + top }}>
              <span className="font-mono font-semibold text-ink">{r.label}</span>
              <span className="ml-2 text-ink-2">{r.start} → {r.end}</span>
            </div>
          )
        })()}
      </div>
    </ChartFrame>
  )
}
