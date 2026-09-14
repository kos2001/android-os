import { Activity, CheckCircle2, CircleCheckBig, Gauge, OctagonX, Pause, Play, RefreshCw, ShieldCheck, SkipForward, Undo2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { BarList, LineChart, SegmentBar } from '../components/charts/charts'
import { PageHeader, StatTile } from '../components/layout'
import { ConfirmDialog, useToast } from '../components/ui/overlay'
import { Button, Card, CardHeader, ErrorBanner, KeyValue, Mono, Segmented, Skeleton } from '../components/ui/primitives'
import { ASSIGNMENT_LABEL, Badge, ChannelBadge, RolloutBadge } from '../components/ui/status'
import { api, type AssignmentState, type HaltEvaluation, type Rollout } from '../lib/api'
import { dateTime, num, pct, relativeTime, shortFingerprint } from '../lib/format'
import { useAsync } from '../lib/hooks'

type Action = 'start' | 'promote' | 'pause' | 'resume' | 'halt' | 'complete'

const ACTION: Record<Action, { label: string; icon: ReactNode; confirm: string; description: string; danger?: boolean; reason?: boolean }> = {
  start: { label: '시작', icon: <Play className="size-3.5" />, confirm: '롤아웃을 시작할까요?', description: '1단계 비율의 기기에 즉시 제공됩니다.' },
  promote: { label: '다음 단계', icon: <SkipForward className="size-3.5" />, confirm: '다음 단계로 승격할까요?', description: '비율을 올리면 기존 대상은 유지되고 새 기기가 추가됩니다. 최소 유지 시간이 지나야 합니다.' },
  pause: { label: '일시정지', icon: <Pause className="size-3.5" />, confirm: '일시정지할까요?', description: '신규 제공이 멈춥니다. 다운로드·설치 중인 기기는 계속 진행합니다.' },
  resume: { label: '재개', icon: <Play className="size-3.5" />, confirm: '재개할까요?', description: '현재 단계 비율로 다시 제공합니다.' },
  halt: { label: '중단', icon: <OctagonX className="size-3.5" />, confirm: '롤아웃을 중단할까요?', description: '중단된 롤아웃은 재개할 수 없습니다. 이미 새 빌드로 부팅한 기기는 되돌릴 수 없으며, 수정 빌드로 새 롤아웃을 만들어야 합니다.', danger: true, reason: true },
  complete: { label: '완료', icon: <CircleCheckBig className="size-3.5" />, confirm: '롤아웃을 완료 처리할까요?', description: '더 이상 기기에 제공하지 않습니다.' },
}

const AVAILABLE: Record<Rollout['state'], Action[]> = {
  draft: ['start'], active: ['promote', 'pause', 'halt', 'complete'], paused: ['resume', 'halt', 'complete'],
  halted: ['complete'], completed: [],
}

const ASSIGNMENT_COLORS: Record<AssignmentState, string> = {
  offered: 'var(--axis)', downloading: 'var(--series-1)', installed_pending_reboot: '#86b6ef',
  boot_success: '#0ca30c', boot_fallback: '#ec835a', failed: '#d03b3b',
}

export default function RolloutDetailPage({ id }: { id: number }) {
  const toast = useToast()
  const [hours, setHours] = useState<'24' | '72' | '168'>('72')
  const rollout = useAsync(() => api.rollout(id), [id], 15_000)
  const metrics = useAsync(() => api.metrics(id), [id], 15_000)
  const series = useAsync(() => api.timeseries(id, Number(hours)), [id, hours], 30_000)
  const [action, setAction] = useState<Action | null>(null)
  const [evaluation, setEvaluation] = useState<HaltEvaluation>()
  const [evaluating, setEvaluating] = useState(false)

  const r = rollout.data
  const m = metrics.data
  const reload = () => { rollout.reload(); metrics.reload(); series.reload() }

  if (rollout.error) return <ErrorBanner error={rollout.error} onRetry={rollout.reload} />
  if (!r) return <div className="space-y-4"><Skeleton className="h-12 w-1/3" /><Skeleton className="h-72" /></div>

  const w = m?.window
  const errorRate = w && w.attempted ? Object.values(w.failed_by_code).reduce((a, b) => a + b, 0) / w.attempted : null
  const fallbackRate = w && w.installed ? w.boot_fallback / w.installed : null
  const nextStage = r.stages[r.current_stage]
  const soakUntil = r.current_stage > 0 && r.stages[r.current_stage - 1].promoted_at
    ? new Date(new Date(r.stages[r.current_stage - 1].promoted_at!).getTime() + r.stages[r.current_stage - 1].min_soak_hours * 3600_000)
    : null

  const evaluate = async () => {
    setEvaluating(true)
    try {
      setEvaluation(await api.evaluateHalt(id, false))
    } catch (e) {
      toast({ kind: 'error', title: '평가 실패', description: (e as Error).message })
    } finally {
      setEvaluating(false)
    }
  }

  return (
    <>
      <PageHeader
        title={r.name}
        description={shortFingerprint(r.target_fingerprint)}
        meta={<><RolloutBadge state={r.state} /><ChannelBadge channel={r.channel} /><Badge>{r.device}</Badge>
          <span className="text-xs text-muted">{r.created_by} · {relativeTime(r.created_at)}</span></>}
        actions={<>
          <Button variant="ghost" icon={<RefreshCw className="size-3.5" />} onClick={reload}>새로고침</Button>
          {AVAILABLE[r.state].map((a) => (
            <Button key={a} variant={a === 'halt' ? 'danger' : a === 'start' || a === 'promote' ? 'primary' : 'secondary'}
              icon={ACTION[a].icon} onClick={() => setAction(a)}>{ACTION[a].label}</Button>
          ))}
        </>}
      />

      {r.state === 'halted' && r.halt_reason && (
        <div role="alert" className="mb-4 flex gap-2.5 rounded-lg border border-critical/30 bg-critical/5 px-4 py-3">
          <OctagonX className="mt-0.5 size-4 shrink-0 text-critical" />
          <div className="text-[13px]"><p className="font-semibold text-ink">중단됨</p><p className="mt-0.5 text-ink-2">{r.halt_reason}</p></div>
        </div>
      )}

      <Card className="mb-4">
        <div className="p-4">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-[13px] font-semibold text-ink">배포 단계</p>
            <p className="text-xs text-muted">
              현재 <b className="tabular text-ink">{r.current_percent}%</b>
              {nextStage && soakUntil && ` · 다음 단계(${nextStage.percent}%) 승격 가능: ${soakUntil <= new Date() ? '지금' : dateTime(soakUntil.toISOString())}`}
            </p>
          </div>
          <ol className="grid gap-2" style={{ gridTemplateColumns: `repeat(${r.stages.length}, minmax(0, 1fr))` }}>
            {r.stages.map((s) => {
              const done = s.seq < r.current_stage
              const current = s.seq === r.current_stage
              return (
                <li key={s.seq} className={`rounded-md border px-3 py-2.5 ${current ? 'border-accent bg-accent/5' : 'border-line'}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted">{s.seq}단계</span>
                    {done && <CheckCircle2 className="size-3.5 text-good" />}
                    {current && <Activity className="size-3.5 text-accent-ink" />}
                  </div>
                  <p className="tabular mt-1 text-lg font-semibold text-ink">{s.percent}%</p>
                  <p className="text-[11px] text-muted">
                    {s.promoted_at ? `${relativeTime(s.promoted_at)} · ${s.promoted_by}` : `최소 ${s.min_soak_hours}시간 유지`}
                  </p>
                </li>
              )
            })}
          </ol>
        </div>
      </Card>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile icon={<Gauge className="size-3.5" />} label="설치 시도" value={w ? num(w.attempted) : '—'} sub="attempt 단위" />
        <StatTile icon={<ShieldCheck className="size-3.5" />} label="부팅 판정" value={w ? num(w.installed) : '—'}
          sub={w?.attempted ? `시도 대비 ${pct(w.installed / w.attempted)}` : undefined} />
        <StatTile icon={<OctagonX className="size-3.5" />} label="설치 실패율" value={pct(errorRate)}
          sub={r.halt_rules.max_error_rate != null ? `중단 기준 ${pct(r.halt_rules.max_error_rate)}` : '기준 없음'} />
        <StatTile icon={<Undo2 className="size-3.5" />} label="부팅 폴백률" value={pct(fallbackRate)}
          sub={r.halt_rules.max_boot_fallback_rate != null ? `중단 기준 ${pct(r.halt_rules.max_boot_fallback_rate)}` : '기준 없음'} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="p-4">
            {series.data ? (
              <LineChart
                title="설치 진행 추이"
                subtitle="시간당 이벤트 수 (서버 수신 기준)"
                data={series.data}
                x="hour"
                formatX={(v) => { const d = new Date(v); return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}시` }}
                series={[
                  { key: 'download_started', label: '다운로드 시작', color: 'var(--series-1)' },
                  { key: 'updated_need_reboot', label: '설치 완료', color: 'var(--series-2)' },
                  { key: 'boot_success', label: '부팅 성공', color: 'var(--series-3)' },
                ]}
              />
            ) : <Skeleton className="h-64" />}
            <div className="mt-2 flex justify-end">
              <Segmented value={hours} onChange={setHours} items={[
                { value: '24', label: '24시간' }, { value: '72', label: '3일' }, { value: '168', label: '7일' }]} />
            </div>
          </div>
        </Card>
        <Card>
          <CardHeader title="기기 상태" description="assignment 현재 상태" />
          <div className="p-4">
            {m ? (
              <SegmentBar segments={(Object.keys(ASSIGNMENT_LABEL) as AssignmentState[]).map((s) => ({
                key: s, label: ASSIGNMENT_LABEL[s], value: m.assignments[s] ?? 0, color: ASSIGNMENT_COLORS[s] }))} />
            ) : <Skeleton className="h-20" />}
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <div className="p-4">
            <BarList
              title="설치 실패 오류 코드"
              subtitle="update_engine ErrorCode · 시도별 마지막 실패 기준"
              valueLabel="기기 수"
              items={(m?.errors ?? []).map((e) => ({
                key: String(e.code), value: e.devices, hint: `ErrorCode ${e.code}`,
                label: <span><Mono className="text-muted">{e.code}</Mono> {e.name}</span>,
              }))}
              empty={<p className="py-8 text-center text-xs text-muted">기록된 설치 실패가 없습니다</p>}
            />
          </div>
        </Card>
        <Card>
          <CardHeader title="자동 중단 규칙" actions={
            <Button size="sm" loading={evaluating} onClick={evaluate}>지금 평가</Button>} />
          <div className="space-y-4 p-4">
            <KeyValue items={[
              ['최소 표본', num(r.halt_rules.min_sample)],
              ['설치 실패율', r.halt_rules.max_error_rate != null ? `> ${pct(r.halt_rules.max_error_rate)}` : '—'],
              ['부팅 폴백률', r.halt_rules.max_boot_fallback_rate != null ? `> ${pct(r.halt_rules.max_boot_fallback_rate)}` : '—'],
              ['오류 코드별', Object.keys(r.halt_rules.max_error_code_rate).length
                ? Object.entries(r.halt_rules.max_error_code_rate).map(([c, v]) => `${c}: > ${pct(v)}`).join(', ') : '—'],
              ['중단 시', r.halt_mode === 'stop_new' ? '신규 할당만 중단' : '진행 중 기기도 중단'],
            ]} />
            {evaluation && (
              <div className={`rounded-md border px-3 py-2.5 text-xs ${evaluation.halt ? 'border-critical/30 bg-critical/5' : 'border-good/30 bg-good/5'}`}>
                <p className="font-semibold text-ink">{evaluation.halt ? '중단 기준 초과' : '기준 이내'}</p>
                {evaluation.reasons.map((reason) => <p key={reason} className="mt-0.5 text-ink-2">{reason}</p>)}
                {!evaluation.halt && <p className="mt-0.5 text-muted">시도 {evaluation.window.attempted} · 판정 {evaluation.window.installed}</p>}
              </div>
            )}
          </div>
          <div className="border-t border-line p-4">
            <p className="mb-2 text-xs font-medium text-muted">기기 정책</p>
            <KeyValue items={[
              ['네트워크', r.policy.require_unmetered ? '비측정 네트워크만' : '제한 없음'],
              ['최소 배터리', `${r.policy.min_battery_pct}%`],
              ['최대 시도', `${r.policy.max_attempts}회`],
              ['체크 주기', `${Math.round(r.policy.check_interval_s / 3600)}시간 ±10%`],
            ]} />
          </div>
        </Card>
      </div>

      {action && (
        <ConfirmDialog open onClose={() => setAction(null)} title={ACTION[action].confirm} description={ACTION[action].description}
          confirmLabel={ACTION[action].label} danger={ACTION[action].danger} requireReason={ACTION[action].reason}
          onConfirm={async (reason) => {
            try {
              await api.transition(id, action, reason || undefined)
              toast({ kind: 'success', title: `${ACTION[action].label} 완료` })
              reload()
            } catch (e) {
              toast({ kind: 'error', title: `${ACTION[action].label} 실패`, description: (e as Error).message })
              throw e
            }
          }} />
      )}
    </>
  )
}
