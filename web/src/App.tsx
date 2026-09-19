import type { ReactNode } from 'react'
import { AppShell, Breadcrumbs, NAV } from './components/layout'
import { useRoute } from './lib/hooks'
import { tr, useLang } from './lib/i18n'
import AboutPage from './pages/About'
import AuditPage from './pages/Audit'
import DeltaPage from './pages/Delta'
import KnowledgePage from './pages/Knowledge'
import OverviewPage from './pages/Overview'
import PackagesPage from './pages/Packages'
import PlatformDetailPage from './pages/PlatformDetail'
import PlatformsPage from './pages/Platforms'
import RolloutDetailPage from './pages/RolloutDetail'
import RolloutsPage from './pages/Rollouts'
import SettingsPage from './pages/Settings'
import VintfPage from './pages/Vintf'

function labelOf(path: string): string {
  const label = NAV.flatMap((g) => g.items).find((i) => i.path === path)?.label
  return label ? tr(...label) : path
}

export default function App() {
  const { segments } = useRoute()
  useLang() // 언어가 바뀌면 전체 트리를 다시 렌더한다
  const [section, id] = segments
  const base = `/${section ?? 'overview'}`
  const numericId = id ? Number(id) : NaN

  let page: ReactNode
  const crumbs: { label: ReactNode; href?: string }[] = [{ label: labelOf(base), href: id ? `#${base}` : undefined }]

  switch (section) {
    case 'platforms':
      page = Number.isFinite(numericId) ? <PlatformDetailPage id={numericId} /> : <PlatformsPage />
      if (Number.isFinite(numericId)) crumbs.push({ label: `#${numericId}` })
      break
    case 'rollouts':
      page = Number.isFinite(numericId) ? <RolloutDetailPage id={numericId} /> : <RolloutsPage />
      if (Number.isFinite(numericId)) crumbs.push({ label: `#${numericId}` })
      break
    case 'about': page = <AboutPage />; break
    case 'knowledge': page = <KnowledgePage />; break
    case 'vintf': page = <VintfPage />; break
    case 'packages': page = <PackagesPage />; break
    case 'delta': page = <DeltaPage />; break
    case 'audit': page = <AuditPage />; break
    case 'settings': page = <SettingsPage />; break
    default: page = <OverviewPage />
  }

  return (
    <AppShell crumbs={<Breadcrumbs items={crumbs} />}>
      <div key={segments.join('/')} className="animate-fade-in">{page}</div>
    </AppShell>
  )
}
