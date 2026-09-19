import { AlertOctagon, Boxes, Cpu, RefreshCw, Rocket, ShieldCheck, Smartphone, Undo2, XCircle } from 'lucide-react'
import { SegmentBar } from '../components/charts/charts'
import { PageHeader, StatTile } from '../components/layout'
import { Badge, ReadyBadge } from '../components/ui/status'
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Skeleton } from '../components/ui/primitives'
import { api } from '../lib/api'
import { num, pct, relativeTime } from '../lib/format'
import { navigate, useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'

export default function OverviewPage() {
  const t = useT()
  const ov = useAsync(() => api.overview(), [], 15_000)
  const d = ov.data
  const outcomes = d ? d.boot_success_24h + d.boot_fallback_24h : 0

  return (
    <>
      <PageHeader
        title={t('개요', 'Overview')}
        description={t('플랫폼 업그레이드 준비도와 OTA 배포 현황을 한눈에 봅니다. 15초마다 갱신됩니다.', 'Platform upgrade readiness and OTA rollout status at a glance. Refreshes every 15 seconds.')}
        meta={d && <>
          <Badge>KB {d.kb_version}</Badge>
          {d.dev_mode && <Badge tone="warning" icon={<AlertOctagon className="size-3" />}>{t('개발 모드 · 인증 꺼짐', 'Dev mode · auth off')}</Badge>}
        </>}
        actions={<Button icon={<RefreshCw className="size-3.5" />} onClick={ov.reload}>{t('새로고침', 'Refresh')}</Button>}
      />
      {ov.error && <div className="mb-4"><ErrorBanner error={ov.error} onRetry={ov.reload} /></div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!d ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[92px] rounded-lg" />) : <>
          <StatTile icon={<Smartphone className="size-3.5" />} label={t('24시간 체크인 기기', 'Devices checked in (24h)')} value={num(d.devices_checked_in_24h)} />
          <StatTile icon={<ShieldCheck className="size-3.5" />} label={t('부팅 성공 (24h)', 'Boot success (24h)')} value={num(d.boot_success_24h)}
            sub={outcomes ? t(`판정 ${num(outcomes)}건 중 ${pct(d.boot_success_24h / outcomes)}`, `${pct(d.boot_success_24h / outcomes)} of ${num(outcomes)} outcomes`) : t('판정된 설치 없음', 'No install outcomes')} />
          <StatTile icon={<Undo2 className="size-3.5" />} label={t('부팅 폴백 (24h)', 'Boot fallback (24h)')} value={num(d.boot_fallback_24h)}
            sub={t('새 슬롯 부팅 실패 후 이전 빌드', 'Reverted to previous build after new slot failed to boot')} />
          <StatTile icon={<XCircle className="size-3.5" />} label={t('설치 실패 (24h)', 'Install failures (24h)')} value={num(d.install_failures_24h)}
            sub={t('사용자 취소 제외', 'Excludes user cancellations')} />
        </>}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title={t('플랫폼 준비도', 'Platform readiness')} description={t('플랫폼별 최신 판정 결과', 'Latest check result per platform')}
            actions={<Button size="sm" variant="ghost" onClick={() => navigate('/platforms')}>{t('전체 보기', 'View all')}</Button>} />
          {!d ? <div className="space-y-3 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
            : d.platforms.length === 0 ? (
              <EmptyState icon={<Cpu className="size-5" />} title={t('등록된 플랫폼이 없습니다', 'No platforms registered')}
                description={t('플랫폼 프로파일을 등록하면 목표 Android 릴리스 대비 blocker 를 판정합니다.', 'Register a platform profile to check for blockers against a target Android release.')}
                action={<Button variant="primary" onClick={() => navigate('/platforms?new=1')}>{t('플랫폼 등록', 'Register platform')}</Button>} />
            ) : (
              <ul className="divide-y divide-line">
                {d.platforms.map((p) => (
                  <li key={p.id}>
                    <a href={`#/platforms/${p.id}`} className="flex items-center gap-4 px-4 py-3 hover:bg-page">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-medium text-ink">{p.name}</p>
                        <p className="mt-0.5 text-xs text-muted">{p.soc} · Android {p.android_version} · <span className="font-mono">{p.kernel_branch}</span></p>
                      </div>
                      {p.latest_run ? (
                        <div className="flex items-center gap-3 text-right">
                          <div className="hidden text-xs text-muted sm:block">
                            → Android {p.latest_run.target_release}<br />{relativeTime(p.latest_run.created_at)}
                          </div>
                          <ReadyBadge ready={p.latest_run.ready} />
                        </div>
                      ) : <ReadyBadge ready={null} />}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          {d && (d.open_work_items.blocker || d.open_work_items.warning) ? (
            <div className="border-t border-line px-4 py-3 text-xs text-ink-2">
              {t('미해결 작업 항목', 'Open work items')} · Blocker <b className="text-ink">{num(d.open_work_items.blocker ?? 0)}</b> · Warning <b className="text-ink">{num(d.open_work_items.warning ?? 0)}</b>
            </div>
          ) : null}
        </Card>

        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardHeader title={t('롤아웃', 'Rollouts')} description={t('상태별 개수', 'Count by status')}
              actions={<Button size="sm" variant="ghost" onClick={() => navigate('/rollouts')}>{t('전체 보기', 'View all')}</Button>} />
            <div className="p-4">
              {!d ? <Skeleton className="h-14" /> : (
                <SegmentBar segments={[
                  { key: 'active', label: t('진행 중', 'Active'), value: d.rollouts.active ?? 0, color: 'var(--series-1)', icon: <Rocket className="size-3" /> },
                  { key: 'paused', label: t('일시정지', 'Paused'), value: d.rollouts.paused ?? 0, color: '#fab219' },
                  { key: 'halted', label: t('중단됨', 'Halted'), value: d.rollouts.halted ?? 0, color: '#d03b3b' },
                  { key: 'completed', label: t('완료', 'Completed'), value: d.rollouts.completed ?? 0, color: '#0ca30c' },
                  { key: 'draft', label: t('초안', 'Draft'), value: d.rollouts.draft ?? 0, color: 'var(--axis)' },
                ]} />
              )}
            </div>
          </Card>
          <Card>
            <CardHeader title={t('OTA 패키지', 'OTA packages')} description={t('등록 상태별 개수', 'Count by registration status')}
              actions={<Button size="sm" variant="ghost" onClick={() => navigate('/packages')}>{t('전체 보기', 'View all')}</Button>} />
            <div className="p-4">
              {!d ? <Skeleton className="h-14" /> : (
                <SegmentBar segments={[
                  { key: 'ready', label: 'Ready', value: d.packages.ready ?? 0, color: '#0ca30c', icon: <Boxes className="size-3" /> },
                  { key: 'rejected', label: 'Rejected', value: d.packages.rejected ?? 0, color: '#d03b3b' },
                  { key: 'retired', label: 'Retired', value: d.packages.retired ?? 0, color: 'var(--axis)' },
                ]} />
              )}
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
