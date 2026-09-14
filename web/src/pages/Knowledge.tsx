import { ExternalLink } from 'lucide-react'
import { RangeTimeline } from '../components/charts/charts'
import { PageHeader } from '../components/layout'
import { Card, CardHeader, ErrorBanner, Mono, Skeleton } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api } from '../lib/api'
import { useAsync } from '../lib/hooks'

export default function KnowledgePage() {
  const kb = useAsync(() => api.kb(), [])
  const today = new Date()
  const latest = kb.data?.releases.find((r) => r.release === '17')

  return (
    <>
      <PageHeader title="릴리스 지식베이스"
        description="판정 규칙이 사용하는 사실. 모든 항목은 출처(Google 공식 문서·AOSP 릴리스 태그)와 신뢰도를 가집니다."
        meta={kb.data && <Badge>KB {kb.data.kb_version}</Badge>} />
      {kb.error && <ErrorBanner error={kb.error} onRetry={kb.reload} />}
      {!kb.data ? <Skeleton className="h-96" /> : (
        <div className="space-y-4">
          <Card>
            <CardHeader title="Android 릴리스" description="지원 커널, 소스 트리의 FCM matrix 레벨, 최신 CTS" />
            <DataTable
              rows={kb.data.releases}
              rowKey={(r) => r.release}
              columns={[
                { key: 'release', header: '릴리스', className: 'whitespace-nowrap', cell: (r) => (
                  <span className="flex items-center gap-2 font-medium">Android {r.release}
                    {r.status === 'beta' && <Badge tone="warning">베타</Badge>}</span>) },
                { key: 'api', header: 'API', cell: (r) => <span className="tabular">{r.api_level}</span> },
                { key: 'released', header: '출시', className: 'whitespace-nowrap', cell: (r) => r.released ?? <span className="text-muted">—</span> },
                { key: 'fcm', header: 'FCM 레벨', cell: (r) => r.fcm_level
                  ? <span className="flex items-center gap-1.5">{r.fcm_level}{r.fcm_level_confidence !== 'primary' && <Badge tone="warning">미확인</Badge>}</span>
                  : <span className="text-muted">—</span> },
                { key: 'matrices', header: '트리의 matrix', cell: (r) => (
                  <span className="text-xs text-ink-2">{r.fcm_matrices_in_tree?.join(' · ') ?? '—'}</span>) },
                { key: 'kernels', header: '지원 커널', cell: (r) => (
                  <div className="flex max-w-md flex-wrap gap-1">
                    {r.supported_kernels.map((k) => (
                      <Badge key={k} tone={r.kernels_unsupported_from?.[k] ? 'warning' : 'neutral'}>
                        <Mono className="text-[11px]">{k}</Mono>
                        {r.kernels_unsupported_from?.[k] && <span>· {r.kernels_unsupported_from[k]}~ 불가</span>}
                      </Badge>
                    ))}
                  </div>) },
                { key: 'cts', header: 'CTS', className: 'whitespace-nowrap', cell: (r) => r.latest_cts ?? <span className="text-muted">—</span> },
                { key: 'src', header: '출처', align: 'right', className: 'whitespace-nowrap', cell: (r) => (
                  <a href={r.sources[0]} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent-ink hover:underline">
                    {r.sources.length}개 <ExternalLink className="size-3" /></a>) },
              ]}
            />
          </Card>
          <Card>
            <div className="p-4">
              <RangeTimeline
                title="GKI 커널 브랜치 지원 기간"
                subtitle={`android15-6.6 부터 지원 기간이 6년 → 4년. 회색은 EOL 경과${latest ? ` · 굵게: Android 17 지원 커널` : ''}`}
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
