import { Activity, BookOpen, Info, Boxes, ChevronRight, Command, Cpu, FileDiff, GitCompareArrows, KeyRound, LayoutDashboard,
  Languages, Menu, Monitor, Moon, Rocket, ScrollText, Search, Sun } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, type Health } from '../lib/api'
import { navigate, useAsync, useHotkey, useRoute, useTheme, type ThemeChoice } from '../lib/hooks'
import { tr, useLang } from '../lib/i18n'
import { cx, Kbd } from './ui/primitives'

// 라벨은 [한국어, English]. 렌더 시 tr(...) 로 고른다. keywords 는 두 언어 검색용.
export const NAV: { group: [string, string] | null; items: { path: string; label: [string, string]; icon: ReactNode; keywords?: string }[] }[] = [
  {
    group: null,
    items: [
      { path: '/about', label: ['소개', 'About'], icon: <Info className="size-4" />, keywords: 'about intro introduction 소개 서비스' },
      { path: '/overview', label: ['개요', 'Overview'], icon: <LayoutDashboard className="size-4" />, keywords: 'overview dashboard 개요' },
    ],
  },
  {
    group: ['업그레이드 준비', 'Upgrade readiness'],
    items: [
      { path: '/platforms', label: ['플랫폼', 'Platforms'], icon: <Cpu className="size-4" />, keywords: 'readiness platform bsp' },
      { path: '/knowledge', label: ['릴리스 지식베이스', 'Release knowledge base'], icon: <BookOpen className="size-4" />, keywords: 'kb kernel gki fcm' },
      { path: '/vintf', label: ['VINTF 비교', 'VINTF compare'], icon: <FileDiff className="size-4" />, keywords: 'matrix diff hal' },
    ],
  },
  {
    group: ['OTA 배포', 'OTA delivery'],
    items: [
      { path: '/packages', label: ['패키지', 'Packages'], icon: <Boxes className="size-4" />, keywords: 'ota package zip' },
      { path: '/rollouts', label: ['롤아웃', 'Rollouts'], icon: <Rocket className="size-4" />, keywords: 'rollout staged deploy' },
      { path: '/delta', label: ['Delta 후보', 'Delta candidates'], icon: <GitCompareArrows className="size-4" />, keywords: 'incremental delta report' },
    ],
  },
  {
    group: ['관리', 'Administration'],
    items: [
      { path: '/audit', label: ['감사 로그', 'Audit log'], icon: <ScrollText className="size-4" />, keywords: 'audit log' },
      { path: '/settings', label: ['설정', 'Settings'], icon: <KeyRound className="size-4" />, keywords: 'settings api key theme language 설정 언어' },
    ],
  },
]

function Sidebar({ health, className, onNavigate }: { health?: Health; className?: string; onNavigate?: () => void }) {
  const { path } = useRoute()
  return (
    <aside className={cx('w-56 shrink-0 flex-col border-r border-line bg-surface', className)}>
      <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
        <div className="flex size-7 items-center justify-center rounded-lg bg-accent text-white shadow-sm">
          <Activity className="size-4" />
        </div>
        <div className="leading-tight">
          <p className="text-[13px] font-semibold text-ink">OS Upgrade</p>
          <p className="text-[11px] text-muted">{tr('Android 플랫폼 콘솔', 'Android platform console')}</p>
        </div>
      </div>
      <nav className="scrollbar-thin flex-1 space-y-4 overflow-y-auto px-2 py-3">
        {NAV.map((group) => (
          <div key={group.items[0].path}>
            {group.group && <p className="mb-1 px-2 text-[11px] font-medium text-muted">{tr(...group.group)}</p>}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = path === item.path || path.startsWith(item.path + '/')
                return (
                  <li key={item.path}>
                    <a href={`#${item.path}`} onClick={onNavigate}
                      className={cx('flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] transition-colors',
                        active ? 'bg-accent/10 font-medium text-ink' : 'text-ink-2 hover:bg-line/50 hover:text-ink')}>
                      <span className={active ? 'text-accent-ink' : 'text-muted'}>{item.icon}</span>
                      {tr(...item.label)}
                    </a>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className="border-t border-line px-4 py-3 text-[11px] text-muted">
        <p className="flex items-center gap-1.5">
          <span className={cx('size-1.5 rounded-full', health ? 'bg-good' : 'bg-critical')} aria-hidden />
          {health ? `${tr('API 연결됨', 'API connected')} · v${health.version}` : tr('API 연결 안 됨', 'API disconnected')}
        </p>
        {health && <p className="mt-0.5">KB {health.kb_version}</p>}
      </div>
    </aside>
  )
}

const THEME_ICON: Record<ThemeChoice, ReactNode> = {
  system: <Monitor className="size-4" />, light: <Sun className="size-4" />, dark: <Moon className="size-4" />,
}

export function Breadcrumbs({ items }: { items: { label: ReactNode; href?: string }[] }) {
  return (
    <ol className="flex min-w-0 items-center gap-1 text-[13px]">
      {items.map((item, i) => (
        <li key={i} className="flex min-w-0 items-center gap-1">
          {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted" />}
          {item.href ? <a href={item.href} className="truncate text-muted hover:text-ink">{item.label}</a>
            : <span className="truncate font-medium text-ink">{item.label}</span>}
        </li>
      ))}
    </ol>
  )
}

function Topbar({ onOpenPalette, onOpenMenu, crumbs }: { onOpenPalette: () => void; onOpenMenu: () => void; crumbs: ReactNode }) {
  const [theme, setTheme] = useTheme()
  const [lang, setLang] = useLang()
  const order: ThemeChoice[] = ['system', 'light', 'dark']
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-page/85 px-4 backdrop-blur md:px-6">
      <button onClick={onOpenMenu} aria-label={tr('메뉴 열기', 'Open menu')}
        className="flex size-8 items-center justify-center rounded-md text-ink-2 hover:bg-line/50 hover:text-ink md:hidden">
        <Menu className="size-4" />
      </button>
      <div className="min-w-0 flex-1">{crumbs}</div>
      <button onClick={onOpenPalette}
        className="hidden h-8 w-64 items-center gap-2 rounded-md border border-line bg-raised px-2.5 text-[13px] text-muted shadow-sm transition hover:text-ink sm:flex">
        <Search className="size-4" />
        <span className="flex-1 text-left">{tr('검색 또는 이동…', 'Search or jump to…')}</span>
        <Kbd><Command className="size-2.5" /></Kbd><Kbd>K</Kbd>
      </button>
      <button onClick={onOpenPalette} aria-label={tr('검색', 'Search')}
        className="flex size-8 items-center justify-center rounded-md text-ink-2 hover:bg-line/50 hover:text-ink sm:hidden">
        <Search className="size-4" />
      </button>
      <button
        onClick={() => setTheme(order[(order.indexOf(theme) + 1) % order.length])}
        className="flex size-8 items-center justify-center rounded-md text-ink-2 hover:bg-line/50 hover:text-ink"
        aria-label={`${tr('테마', 'Theme')}: ${theme}`}
        title={`${tr('테마', 'Theme')}: ${{ system: tr('시스템', 'System'), light: tr('라이트', 'Light'), dark: tr('다크', 'Dark') }[theme]}`}>
        {THEME_ICON[theme]}
      </button>
      <button onClick={() => setLang(lang === 'ko' ? 'en' : 'ko')}
        className="flex h-8 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-ink-2 hover:bg-line/50 hover:text-ink"
        aria-label={lang === 'ko' ? 'Switch to English' : '한국어로 전환'} title={lang === 'ko' ? 'English' : '한국어'}>
        <Languages className="size-4" />{lang === 'ko' ? 'EN' : '한'}
      </button>
    </header>
  )
}

interface PaletteItem { id: string; label: string; hint: string; path: string; icon: ReactNode; keywords?: string }
interface DynamicItem { id: string; label: string; kind: 'platform' | 'rollout'; detail: string; path: string; icon: ReactNode }

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const [lang] = useLang()
  const dynamic = useAsync(async (): Promise<DynamicItem[]> => {
    if (!open) return []
    const [platforms, rollouts] = await Promise.all([api.platforms().catch(() => []), api.rollouts().catch(() => [])])
    return [
      ...platforms.map((p): DynamicItem => ({ id: `p${p.id}`, label: p.name, kind: 'platform', detail: p.soc,
        path: `/platforms/${p.id}`, icon: <Cpu className="size-4" /> })),
      ...rollouts.map((r): DynamicItem => ({ id: `r${r.id}`, label: r.name, kind: 'rollout', detail: r.device,
        path: `/rollouts/${r.id}`, icon: <Rocket className="size-4" /> })),
    ]
  }, [open])

  const items = useMemo(() => {
    const pages: PaletteItem[] = NAV.flatMap((g) => g.items.map((i) => ({
      id: i.path, label: tr(...i.label), hint: g.group ? tr(...g.group) : tr('페이지', 'Page'), path: i.path, icon: i.icon,
      keywords: `${i.label.join(' ')} ${i.keywords ?? ''}` })))
    const records: PaletteItem[] = (dynamic.data ?? []).map((d) => ({ id: d.id, label: d.label, path: d.path, icon: d.icon,
      hint: `${d.kind === 'platform' ? tr('플랫폼', 'Platform') : tr('롤아웃', 'Rollout')} · ${d.detail}` }))
    const all = [...pages, ...records]
    const q = query.trim().toLowerCase()
    return q ? all.filter((i) => `${i.label} ${i.hint} ${i.keywords ?? ''}`.toLowerCase().includes(q)) : all
  }, [query, dynamic.data, lang])

  useEffect(() => {
    if (open) {
      setQuery('')
      setIndex(0)
      window.setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])
  useEffect(() => setIndex(0), [query])

  if (!open) return null
  const go = (item?: PaletteItem) => {
    if (!item) return
    navigate(item.path)
    onClose()
  }
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[14vh]">
      <div className="fixed inset-0 animate-fade-in bg-black/40" onClick={onClose} />
      <div role="dialog" aria-label={tr('명령 팔레트', 'Command palette')}
        className="relative w-full max-w-lg animate-slide-up overflow-hidden rounded-xl border border-line bg-surface shadow-pop">
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Search className="size-4 text-muted" />
          <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setIndex((i) => Math.min(i + 1, items.length - 1)) }
              if (e.key === 'ArrowUp') { e.preventDefault(); setIndex((i) => Math.max(i - 1, 0)) }
              if (e.key === 'Enter') go(items[index])
              if (e.key === 'Escape') onClose()
            }}
            placeholder={tr('페이지, 플랫폼, 롤아웃 검색…', 'Search pages, platforms, rollouts…')}
            className="h-12 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-muted" />
          <Kbd>esc</Kbd>
        </div>
        <ul className="scrollbar-thin max-h-80 overflow-y-auto p-1.5">
          {items.length === 0 && <li className="px-3 py-6 text-center text-muted">{tr('일치하는 항목이 없습니다', 'No matches')}</li>}
          {items.map((item, i) => (
            <li key={item.id}>
              <button onMouseMove={() => setIndex(i)} onClick={() => go(item)}
                className={cx('flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left',
                  i === index ? 'bg-accent/10 text-ink' : 'text-ink-2')}>
                <span className="text-muted">{item.icon}</span>
                <span className="flex-1 truncate text-[13px]">{item.label}</span>
                <span className="text-[11px] text-muted">{item.hint}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export function AppShell({ crumbs, children }: { crumbs: ReactNode; children: ReactNode }) {
  const [palette, setPalette] = useState(false)
  const [menu, setMenu] = useState(false)
  const health = useAsync(() => api.health(), [], 30_000)
  useEffect(() => {
    if (!menu) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setMenu(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menu])
  useHotkey('k', (e) => { e.preventDefault(); setPalette((v) => !v) }, true)
  return (
    <div className="flex h-full">
      <Sidebar health={health.data} className="hidden md:flex" />
      {menu && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 animate-fade-in bg-black/30" onClick={() => setMenu(false)} />
          <Sidebar health={health.data} onNavigate={() => setMenu(false)}
            className="absolute inset-y-0 left-0 flex animate-fade-in shadow-pop" />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenPalette={() => setPalette(true)} onOpenMenu={() => setMenu(true)} crumbs={crumbs} />
        <main className="scrollbar-thin flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1280px] px-4 py-6 md:px-6">{children}</div>
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  )
}

export function PageHeader({ title, description, actions, meta }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; meta?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[13px] text-muted">{description}</p>}
        {meta && <div className="mt-2 flex flex-wrap items-center gap-2">{meta}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function StatTile({ label, value, sub, icon }: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3.5">
      <p className="flex items-center gap-1.5 text-xs text-muted">{icon}{label}</p>
      <p className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
    </div>
  )
}
