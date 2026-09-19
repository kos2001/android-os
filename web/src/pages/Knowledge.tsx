import { BookOpen, ExternalLink, Layers } from 'lucide-react'
import { RangeTimeline } from '../components/charts/charts'
import { PageHeader } from '../components/layout'
import { Card, CardHeader, cx, ErrorBanner, Mono, Skeleton } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'
import { HUE, hueOf } from '../lib/palette'

export default function KnowledgePage() {
  const t = useT()
  const kb = useAsync(() => api.kb(), [])
  const today = new Date()
  const latest = kb.data?.releases.find((r) => r.release === '17')

  return (
    <>
      <PageHeader title={t('릴리스 지식베이스', 'Release knowledge base')}
        description={t('판정 규칙이 사용하는 사실. 모든 항목은 출처(Google 공식 문서·AOSP 릴리스 태그)와 신뢰도를 가집니다.',
          'Facts used by the check rules. Every entry has a source (official Google docs, AOSP release tags) and a confidence level.')}
        meta={kb.data && <Badge hue="teal" icon={<BookOpen className="size-3" />}>KB {kb.data.kb_version}</Badge>} />
      {kb.error && <ErrorBanner error={kb.error} onRetry={kb.reload} />}
      {!kb.data ? <Skeleton className="h-96" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {kb.data.releases.map((r) => { const h = HUE[hueOf(r.release)]; return (
              <div key={r.release} className={cx('rounded-lg border-l-4 bg-surface px-3 py-2.5 ring-1 ring-line', h.border)}>
                <div className="flex items-center gap-2">
                  <span aria-hidden className={cx('grid size-6 shrink-0 place-items-center rounded-md ring-1 ring-inset', h.soft, h.text, h.ring)}>
                    <Layers className="size-3.5" />
                  </span>
                  <span className={cx('text-[13px] font-semibold', h.text)}>Android {r.release}</span>
                </div>
                <p className="mt-1.5 text-xs text-muted">API <span className="tabular text-ink-2">{r.api_level}</span>
                  {r.fcm_level && <> · FCM <span className="tabular text-ink-2">{r.fcm_level}</span></>}</p>
                <p className="text-xs text-muted">{t(`커널 ${r.supported_kernels.length}개`, `${r.supported_kernels.length} kernels`)}
                  {r.status === 'beta' && <> · <span className="text-[#8a5a00] dark:text-warning">{t('베타', 'Beta')}</span></>}</p>
              </div>
            ) })}
          </div>
          <Card>
            <CardHeader hue="teal" title={t('Android 릴리스', 'Android releases')} description={t('지원 커널, 소스 트리의 FCM matrix 레벨, 최신 CTS', 'Supported kernels, FCM matrix levels in the source tree, latest CTS')} />
            <DataTable
              rows={kb.data.releases}
              rowKey={(r) => r.release}
              columns={[
                { key: 'release', header: t('릴리스', 'Release'), className: 'whitespace-nowrap', cell: (r) => (
                  <span className="flex items-center gap-2 font-medium">
                    <Badge hue={hueOf(r.release)}>Android {r.release}</Badge>
                    {r.status === 'beta' && <Badge tone="warning">{t('베타', 'Beta')}</Badge>}</span>) },
                { key: 'api', header: 'API', cell: (r) => <span className="tabular">{r.api_level}</span> },
                { key: 'released', header: t('출시', 'Released'), className: 'whitespace-nowrap', cell: (r) => r.released ?? <span className="text-muted">—</span> },
                { key: 'fcm', header: t('FCM 레벨', 'FCM level'), cell: (r) => r.fcm_level
                  ? <span className="flex items-center gap-1.5">{r.fcm_level}{r.fcm_level_confidence !== 'primary' && <Badge tone="warning">{t('미확인', 'Unverified')}</Badge>}</span>
                  : <span className="text-muted">—</span> },
                { key: 'matrices', header: t('트리의 matrix', 'Matrices in tree'), cell: (r) => (
                  <span className="text-xs text-ink-2">{r.fcm_matrices_in_tree?.join(' · ') ?? '—'}</span>) },
                { key: 'kernels', header: t('지원 커널', 'Supported kernels'), cell: (r) => (
                  <div className="flex max-w-md flex-wrap gap-1">
                    {r.supported_kernels.map((k) => (
                      <Badge key={k} {...(r.kernels_unsupported_from?.[k] ? { tone: 'warning' as const } : { hue: hueOf(k) })}>
                        <Mono className="text-[11px]">{k}</Mono>
                        {r.kernels_unsupported_from?.[k] && <span>· {t(`${r.kernels_unsupported_from[k]}~ 불가`, `not allowed from ${r.kernels_unsupported_from[k]}`)}</span>}
                      </Badge>
                    ))}
                  </div>) },
                { key: 'cts', header: 'CTS', className: 'whitespace-nowrap', cell: (r) => r.latest_cts ?? <span className="text-muted">—</span> },
                { key: 'src', header: t('출처', 'Sources'), align: 'right', className: 'whitespace-nowrap', cell: (r) => (
                  <a href={r.sources[0]} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent-ink hover:underline">
                    {t(`${r.sources.length}개`, `${r.sources.length}`)} <ExternalLink className="size-3" /></a>) },
              ]}
            />
          </Card>
          <Card className="border-t-4 border-t-indigo-400 dark:border-t-indigo-500/60">
            <div className="p-4">
              <RangeTimeline
                title={t('GKI 커널 브랜치 지원 기간', 'GKI kernel branch support periods')}
                subtitle={t('android15-6.6 부터 지원 기간이 6년 → 4년. 회색은 EOL 경과', 'Support period shortened from 6 to 4 years starting with android15-6.6. Gray means past EOL')
                  + (latest ? t(' · 굵게: Android 17 지원 커널', ' · Bold: kernels supported by Android 17') : '')}
                today={today}
                rows={kb.data.kernel_branches.map((k) => ({
                  key: k.branch, label: k.branch, start: k.launch, end: k.eol,
                  highlight: latest?.supported_kernels.includes(k.branch),
                }))}
              />
            </div>
          </Card>
        </div>
      )}
    </>
  )
}
