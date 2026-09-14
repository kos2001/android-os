import { AlertOctagon, Boxes, Cpu, RefreshCw, Rocket, ShieldCheck, Smartphone, Undo2, XCircle } from 'lucide-react'
import { SegmentBar } from '../components/charts/charts'
import { PageHeader, StatTile } from '../components/layout'
import { Badge, ReadyBadge } from '../components/ui/status'
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Skeleton } from '../components/ui/primitives'
import { api } from '../lib/api'
import { num, pct, relativeTime } from '../lib/format'
import { navigate, useAsync } from '../lib/hooks'

export default function OverviewPage() {
  const ov = useAsync(() => api.overview(), [], 15_000)
  const d = ov.data
  const outcomes = d ? d.boot_success_24h + d.boot_fallback_24h : 0

  return (
    <>
      <PageHeader
        title="개요"
        description="플랫폼 업그레이드 준비도와 OTA 배포 현황을 한눈에 봅니다. 15초마다 갱신됩니다."
        meta={d && <>
          <Badge>KB {d.kb_version}</Badge>
          {d.dev_mode && <Badge tone="warning" icon={<AlertOctagon className="size-3" />}>개발 모드 · 인증 꺼짐</Badge>}
        </>}
        actions={<Button icon={<RefreshCw className="size-3.5" />} onClick={ov.reload}>새로고침</Button>}
      />
      {ov.error && <div className="mb-4"><ErrorBanner error={ov.error} onRetry={ov.reload} /></div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!d ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[92px] rounded-lg" />) : <>
          <StatTile icon={<Smartphone className="size-3.5" />} label="24시간 체크인 기기" value={num(d.devices_checked_in_24h)} />
          <StatTile icon={<ShieldCheck className="size-3.5" />} label="부팅 성공 (24h)" value={num(d.boot_success_24h)}
            sub={outcomes ? `판정 ${num(outcomes)}건 중 ${pct(d.boot_success_24h / outcomes)}` : '판정된 설치 없음'} />
          <StatTile icon={<Undo2 className="size-3.5" />} label="부팅 폴백 (24h)" value={num(d.boot_fallback_24h)}
            sub="새 슬롯 부팅 실패 후 이전 빌드" />
          <StatTile icon={<XCircle className="size-3.5" />} label="설치 실패 (24h)" value={num(d.install_failures_24h)}
            sub="사용자 취소 제외" />
        </>}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="플랫폼 준비도" description="플랫폼별 최신 판정 결과"
            actions={<Button size="sm" variant="ghost" onClick={() => navigate('/platforms')}>전체 보기</Button>} />
          {!d ? <div className="space-y-3 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
            : d.platforms.length === 0 ? (
              <EmptyState icon={<Cpu className="size-5" />} title="등록된 플랫폼이 없습니다"
                description="플랫폼 프로파일을 등록하면 목표 Android 릴리스 대비 blocker 를 판정합니다."
                action={<Button variant="primary" onClick={() => navigate('/platforms?new=1')}>플랫폼 등록</Button>} />
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
              미해결 작업 항목 · Blocker <b className="text-ink">{num(d.open_work_items.blocker ?? 0)}</b> · Warning <b className="text-ink">{num(d.open_work_items.warning ?? 0)}</b>
            </div>
          ) : null}
        </Card>

        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardHeader title="롤아웃" description="상태별 개수"
              actions={<Button size="sm" variant="ghost" onClick={() => navigate('/rollouts')}>전체 보기</Button>} />
            <div className="p-4">
              {!d ? <Skeleton className="h-14" /> : (
                <SegmentBar segments={[
                  { key: 'active', label: '진행 중', value: d.rollouts.active ?? 0, color: 'var(--series-1)', icon: <Rocket className="size-3" /> },
                  { key: 'paused', label: '일시정지', value: d.rollouts.paused ?? 0, color: '#fab219' },
                  { key: 'halted', label: '중단됨', value: d.rollouts.halted ?? 0, color: '#d03b3b' },
                  { key: 'completed', label: '완료', value: d.rollouts.completed ?? 0, color: '#0ca30c' },
                  { key: 'draft', label: '초안', value: d.rollouts.draft ?? 0, color: 'var(--axis)' },
                ]} />
              )}
            </div>
          </Card>
          <Card>
            <CardHeader title="OTA 패키지" description="등록 상태별 개수"
              actions={<Button size="sm" variant="ghost" onClick={() => navigate('/packages')}>전체 보기</Button>} />
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
