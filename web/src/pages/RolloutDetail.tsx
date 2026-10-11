import { Activity, BatteryMedium, CheckCircle2, CircleCheckBig, Gauge, Hash, OctagonX, Pause, Play, RefreshCw, RotateCcw, ShieldCheck,
  SkipForward, Timer, Undo2, Users, Wifi, XCircle } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { BarList, LineChart, SegmentBar } from '../components/charts/charts'
import { PageHeader, StatTile } from '../components/layout'
import { ConfirmDialog, useToast } from '../components/ui/overlay'
import { Button, Card, CardHeader, cx, ErrorBanner, KeyValue, Mono, Segmented, Skeleton } from '../components/ui/primitives'
import { ASSIGNMENT_LABEL, Badge, ChannelBadge, RolloutBadge } from '../components/ui/status'
import { api, type AssignmentState, type HaltEvaluation, type Rollout } from '../lib/api'
import { dateTime, num, parseFingerprint, pct, relativeTime, shortFingerprint } from '../lib/format'
import { useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'
import { HUE, hueOf, type Hue } from '../lib/palette'
import { rolloutReason } from '../lib/rollout-reasons'

type Action = 'start' | 'promote' | 'pause' | 'resume' | 'halt' | 'complete'

type Translate = (ko: string, en: string) => string
type ActionMeta = { label: string; icon: ReactNode; confirm: string; description: string; danger?: boolean; reason?: boolean }

const actionMeta = (t: Translate): Record<Action, ActionMeta> => ({
  start: { label: t('시작', 'Start'), icon: <Play className="size-3.5" />, confirm: t('롤아웃을 시작할까요?', 'Start this rollout?'), description: t('1단계 비율의 기기에 즉시 제공됩니다.', 'The update is offered right away to the stage 1 share of devices.') },
  promote: { label: t('다음 단계', 'Next stage'), icon: <SkipForward className="size-3.5" />, confirm: t('다음 단계로 승격할까요?', 'Promote to the next stage?'), description: t('비율을 올리면 기존 대상은 유지되고 새 기기가 추가됩니다. 최소 유지 시간이 지나야 합니다.', 'Raising the percentage keeps existing targets and adds new devices. The minimum soak time must have passed.') },
  pause: { label: t('일시정지', 'Pause'), icon: <Pause className="size-3.5" />, confirm: t('일시정지할까요?', 'Pause this rollout?'), description: t('신규 제공이 멈춥니다. 다운로드·설치 중인 기기는 계속 진행합니다.', 'New offers stop. Devices already downloading or installing continue.') },
  resume: { label: t('재개', 'Resume'), icon: <Play className="size-3.5" />, confirm: t('재개할까요?', 'Resume this rollout?'), description: t('현재 단계 비율로 다시 제공합니다.', 'Offers resume at the current stage percentage.') },
  halt: { label: t('중단', 'Halt'), icon: <OctagonX className="size-3.5" />, confirm: t('롤아웃을 중단할까요?', 'Halt this rollout?'), description: t('중단된 롤아웃은 재개할 수 없습니다. 이미 새 빌드로 부팅한 기기는 되돌릴 수 없으며, 수정 빌드로 새 롤아웃을 만들어야 합니다.', 'A halted rollout cannot be resumed. Devices already booted into the new build cannot be reverted; create a new rollout with a fixed build.'), danger: true, reason: true },
  complete: { label: t('완료', 'Complete'), icon: <CircleCheckBig className="size-3.5" />, confirm: t('롤아웃을 완료 처리할까요?', 'Mark this rollout as complete?'), description: t('더 이상 기기에 제공하지 않습니다.', 'The update will no longer be offered to devices.') },
})

const AVAILABLE: Record<Rollout['state'], Action[]> = {
  draft: ['start'], active: ['promote', 'pause', 'halt', 'complete'], paused: ['resume', 'halt', 'complete'],
  halted: ['complete'], completed: [],
}

// 단계마다 고유 색 (장식용, 롤아웃 목록과 같은 순서)
const STAGE_HUES: Hue[] = ['sky', 'violet', 'fuchsia', 'orange', 'emerald']
const stageHue = (seq: number): Hue => STAGE_HUES[(seq - 1 + STAGE_HUES.length) % STAGE_HUES.length]

/** 규칙·정책 항목 이름 앞 색 아이콘 칩 */
function Chip({ hue, icon, children }: { hue: Hue; icon: ReactNode; children: ReactNode }) {
  const h = HUE[hue]
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden className={cx('flex size-5 shrink-0 items-center justify-center rounded-md ring-1 ring-inset', h.soft, h.text, h.ring)}>{icon}</span>
      {children}
    </span>
  )
}

const ASSIGNMENT_COLORS: Record<AssignmentState, string> = {
  offered: 'var(--axis)', downloading: 'var(--series-1)', installed_pending_reboot: '#86b6ef',
  boot_success: '#0ca30c', boot_fallback: '#ec835a', failed: '#d03b3b',
}

export default function RolloutDetailPage({ id }: { id: number }) {
  const t = useT()
  const toast = useToast()
  const [hours, setHours] = useState<'24' | '72' | '168'>('72')
  const rollout = useAsync(() => api.rollout(id), [id], 15_000)
  const metrics = useAsync(() => api.metrics(id), [id], 15_000)
  const promotion = useAsync(() => api.promotionStatus(id), [id], 15_000)
  const preview = useAsync(() => api.rolloutPreview(id), [id])
  const series = useAsync(() => api.timeseries(id, Number(hours)), [id, hours], 30_000)
  const [action, setAction] = useState<Action | null>(null)
  const [evaluation, setEvaluation] = useState<HaltEvaluation>()
  const [evaluating, setEvaluating] = useState(false)

  const r = rollout.data
  const m = metrics.data
  const reload = () => { rollout.reload(); metrics.reload(); series.reload(); promotion.reload(); preview.reload() }

  if (rollout.error) return <ErrorBanner error={rollout.error} onRetry={rollout.reload} />
  if (!r) return <div className="space-y-4"><Skeleton className="h-12 w-1/3" /><Skeleton className="h-72" /></div>

  const ACTION = actionMeta(t)
  const fp = parseFingerprint(r.target_fingerprint)
  const w = m?.window
  const errorRate = w && w.attempted ? Object.values(w.failed_by_code).reduce((a, b) => a + b, 0) / w.attempted : null
  const fallbackRate = w && w.installed ? w.boot_fallback / w.installed : null
  const nextStage = r.stages[r.current_stage]

  const evaluate = async () => {
    setEvaluating(true)
    try {
      setEvaluation(await api.evaluateHalt(id, false))
    } catch (e) {
      toast({ kind: 'error', title: t('평가 실패', 'Evaluation failed'), description: (e as Error).message })
    } finally {
      setEvaluating(false)
    }
  }

  return (
    <>
      <PageHeader
        title={r.name}
        description={shortFingerprint(r.target_fingerprint)}
        meta={<><RolloutBadge state={r.state} /><ChannelBadge channel={r.channel} /><Badge hue={hueOf(r.device)}>{r.device}</Badge>
          {fp.release && <Badge hue={hueOf(`Android ${fp.release}`)}>Android {fp.release}</Badge>}
          {fp.release && <Badge hue={hueOf(fp.buildId)}><span className="font-mono">{fp.buildId}</span></Badge>}
          <span className="text-xs text-muted">{r.created_by} · {relativeTime(r.created_at)}</span></>}
        actions={<>
          <Button variant="ghost" icon={<RefreshCw className="size-3.5" />} onClick={reload}>{t('새로고침', 'Refresh')}</Button>
          {AVAILABLE[r.state].map((a) => (
            <Button key={a} variant={a === 'halt' ? 'danger' : a === 'start' || a === 'promote' ? 'primary' : 'secondary'}
              disabled={a === 'promote' && (!nextStage || !promotion.data?.can_promote)}
              icon={ACTION[a].icon} onClick={() => setAction(a)}>{ACTION[a].label}</Button>
          ))}
        </>}
      />

      {r.state === 'halted' && r.halt_reason && (
        <div role="alert" className="mb-4 flex gap-2.5 rounded-lg border border-critical/30 bg-critical/5 px-4 py-3">
          <OctagonX className="mt-0.5 size-4 shrink-0 text-critical" />
          <div className="text-[13px]"><p className="font-semibold text-ink">{t('중단됨', 'Halted')}</p><p className="mt-0.5 text-ink-2">{r.halt_reason}</p></div>
        </div>
      )}

      <Card className="mb-4">
        <div className="p-4">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <p className="flex items-center gap-2 text-[13px] font-semibold text-ink">
              <span aria-hidden className={cx('size-2 rounded-full', HUE.orange.dot)} />{t('배포 단계', 'Stages')}</p>
            <p className="text-xs text-muted">
              {t('현재', 'Current')} <b className="tabular text-ink">{r.current_percent}%</b>
              {nextStage && promotion.data && ` · ${t('승격', 'Promotion')}: ${promotion.data.can_promote
                ? t('가능', 'Ready') : promotion.data.reasons.map(rolloutReason).join(' · ')}`}
            </p>
          </div>
          <ol className="grid gap-2" style={{ gridTemplateColumns: `repeat(${r.stages.length}, minmax(0, 1fr))` }}>
            {r.stages.map((s) => {
              const done = s.seq < r.current_stage
              const current = s.seq === r.current_stage
              const h = HUE[stageHue(s.seq)]
              return (
                <li key={s.seq} className={cx('relative overflow-hidden rounded-md px-3 py-2.5 ring-inset',
                  current ? cx(h.soft, h.ring, 'ring-2') : cx('ring-1 ring-line', done && h.soft))}>
                  <div aria-hidden className={cx('absolute inset-x-0 top-0', current ? cx(h.solid, 'h-1.5') : done ? cx(h.dot, 'h-1') : cx(h.soft, 'h-1'))} />
                  <div className="flex items-center justify-between">
                    <span className={cx('flex items-center gap-1.5 text-xs font-medium', h.text)}>
                      <span aria-hidden className={cx('size-2 rounded-full', current || done ? h.dot : cx(h.soft, 'ring-1 ring-inset', h.ring))} />
                      {t(`${s.seq}단계`, `Stage ${s.seq}`)}</span>
                    {done && <CheckCircle2 className="size-3.5 text-good" />}
                    {current && <Activity className={cx('size-3.5', h.text)} />}
                  </div>
                  <p className={cx('tabular mt-1 text-lg font-semibold', current ? h.text : 'text-ink')}>{s.percent}%</p>
                  <p className="text-[11px] text-muted">
                    {s.promoted_at ? `${relativeTime(s.promoted_at)} · ${s.promoted_by}` : t(`최소 ${s.min_soak_hours}시간 유지`, `Soak at least ${s.min_soak_hours}h`)}
                  </p>
                  {(s.min_successful_boots > 0 || s.min_success_rate != null) && <p className="mt-1 text-[11px] text-muted">
                    {t('승격 조건', 'Promotion gates')}: {t(`성공 ≥ ${s.min_successful_boots}`, `Boots ≥ ${s.min_successful_boots}`)}
                    {s.min_success_rate != null && ` · ≥ ${pct(s.min_success_rate)}`}
                  </p>}
                </li>
              )
            })}
          </ol>
          {promotion.error && <div className="mt-3"><ErrorBanner error={promotion.error} onRetry={promotion.reload} /></div>}
          {promotion.data && r.current_stage > 0 && nextStage && <div className="mt-3 rounded-md bg-page p-3 text-xs text-muted">
            <p>{t('전체 롤아웃 이력', 'Whole rollout history')}: {t('부팅 성공', 'Successful boots')} {num(promotion.data.successful_boots)} / {t('설치 시도', 'Install attempts')} {num(promotion.data.attempted)}
              {` · ${t('성공률', 'Success rate')} ${pct(promotion.data.success_rate)}`}</p>
            {promotion.data.soak_until && <p className="mt-1">{t('최소 유지 종료', 'Soak ends')}: {dateTime(promotion.data.soak_until)}</p>}
          </div>}
        </div>
      </Card>

      <Card className="mb-4">
        <CardHeader title={t('배포 대상 미리보기', 'Deployment preview')} hue="blue"
          description={t('같은 모델·채널의 마지막 체크인을 기준으로 이 롤아웃의 제공 가능 여부를 계산합니다. 초안은 첫 단계 비율을 적용합니다. 다른 롤아웃과의 우선순위는 반영하지 않습니다.',
            'Calculates offers for this rollout using the latest check-ins for its model and channel. Drafts use the first-stage percentage. Priority against other rollouts is excluded.')}
          actions={<Button size="sm" loading={preview.loading} onClick={preview.reload}>{t('다시 계산', 'Recalculate')}</Button>} />
        <div className="space-y-3 p-4">
          {!!r.filters.tags?.length && <p className="flex flex-wrap items-center gap-2 text-xs text-muted">{t('대상 태그 (하나 이상 일치)', 'Target tags (match any)')}
            {r.filters.tags.map((tag) => <Badge key={tag} hue={hueOf(tag)}>{tag}</Badge>)}</p>}
          {preview.error && <ErrorBanner error={preview.error} onRetry={preview.reload} />}
          {preview.data ? <>
            <p className="text-sm font-medium">{t('제공 가능', 'Eligible')} {num(preview.data.eligible)} / {num(preview.data.total)}
              <span className="ml-3 text-xs font-normal text-muted">{preview.data.percent}% · full {num(preview.data.packages.full)} · incremental {num(preview.data.packages.incremental)}</span></p>
            <div className="flex flex-wrap gap-2">{Object.entries(preview.data.reasons).map(([reason, count]) =>
              <Badge key={reason} hue={reason === 'ELIGIBLE' ? 'teal' : 'slate'}>{rolloutReason(reason)}: {num(count)}</Badge>)}</div>
            {preview.data.total === 0 && <p className="text-xs text-muted">{t('같은 모델·채널로 체크인한 기기가 없습니다.', 'No devices have checked in with this model and channel.')}</p>}
            <div className="flex flex-wrap gap-2">{preview.data.sample.map((d) => <a key={d.device_hash}
              href={`#/devices/${d.device_hash}`} title={rolloutReason(d.reason)} className="text-xs text-accent hover:underline">
              {d.device_hash.slice(0, 8)}… · {rolloutReason(d.reason)}</a>)}</div>
            <p className="text-[11px] text-muted">{t('계산 시각', 'Calculated at')}: {dateTime(preview.data.as_of)} · {t('최대 20개 기기 표시', 'Showing up to 20 devices')}</p>
          </> : !preview.error && <Skeleton className="h-20" />}
        </div>
      </Card>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile hue="indigo" icon={<Gauge className="size-3.5" />} label={t('설치 시도', 'Install attempts')} value={w ? num(w.attempted) : '—'} sub={t('attempt 단위', 'Per attempt')} />
        <StatTile hue="teal" icon={<ShieldCheck className="size-3.5" />} label={t('부팅 판정', 'Boot verdicts')} value={w ? num(w.installed) : '—'}
          sub={w?.attempted ? t(`시도 대비 ${pct(w.installed / w.attempted)}`, `${pct(w.installed / w.attempted)} of attempts`) : undefined} />
        <StatTile hue="rose" icon={<OctagonX className="size-3.5" />} label={t('설치 실패율', 'Install failure rate')} value={pct(errorRate)}
          sub={r.halt_rules.max_error_rate != null ? t(`중단 기준 ${pct(r.halt_rules.max_error_rate)}`, `Halt threshold ${pct(r.halt_rules.max_error_rate)}`) : t('기준 없음', 'No threshold')} />
        <StatTile hue="amber" icon={<Undo2 className="size-3.5" />} label={t('부팅 폴백률', 'Boot fallback rate')} value={pct(fallbackRate)}
          sub={r.halt_rules.max_boot_fallback_rate != null ? t(`중단 기준 ${pct(r.halt_rules.max_boot_fallback_rate)}`, `Halt threshold ${pct(r.halt_rules.max_boot_fallback_rate)}`) : t('기준 없음', 'No threshold')} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="p-4">
            {series.data ? (
              <LineChart
                title={t('설치 진행 추이', 'Install progress')}
                subtitle={t('시간당 이벤트 수 (서버 수신 기준)', 'Events per hour (by server receipt time)')}
                data={series.data}
                x="hour"
                formatX={(v) => { const d = new Date(v); const hh = String(d.getHours()).padStart(2, '0'); return t(`${d.getMonth() + 1}/${d.getDate()} ${hh}시`, `${d.getMonth() + 1}/${d.getDate()} ${hh}:00`) }}
                series={[
                  { key: 'download_started', label: t('다운로드 시작', 'Download started'), color: 'var(--series-1)' },
                  { key: 'updated_need_reboot', label: t('설치 완료', 'Installed'), color: 'var(--series-2)' },
                  { key: 'boot_success', label: t('부팅 성공', 'Boot success'), color: 'var(--series-3)' },
                ]}
              />
            ) : <Skeleton className="h-64" />}
            <div className="mt-2 flex justify-end">
              <Segmented value={hours} onChange={setHours} items={[
                { value: '24', label: t('24시간', '24h') }, { value: '72', label: t('3일', '3d') }, { value: '168', label: t('7일', '7d') }]} />
            </div>
          </div>
        </Card>
        <Card>
          <CardHeader hue="cyan" title={t('기기 상태', 'Device status')} description={t('assignment 현재 상태', 'Current assignment state')} />
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
              title={t('설치 실패 오류 코드', 'Install failure error codes')}
              subtitle={t('update_engine ErrorCode · 시도별 마지막 실패 기준', 'update_engine ErrorCode · last failure per attempt')}
              valueLabel={t('기기 수', 'Devices')}
              items={(m?.errors ?? []).map((e) => ({
                key: String(e.code), value: e.devices, hint: `ErrorCode ${e.code}`,
                label: <span className="inline-flex items-center gap-1.5">
                  <Mono className={cx('rounded px-1 ring-1 ring-inset', HUE[hueOf(String(e.code))].soft, HUE[hueOf(String(e.code))].text, HUE[hueOf(String(e.code))].ring)}>{e.code}</Mono>
                  {e.name}</span>,
              }))}
              empty={<p className="py-8 text-center text-xs text-muted">{t('기록된 설치 실패가 없습니다', 'No install failures recorded')}</p>}
            />
          </div>
        </Card>
        <Card>
          <CardHeader hue="rose" title={t('자동 중단 규칙', 'Auto-halt rules')} actions={
            <Button size="sm" loading={evaluating} onClick={evaluate}>{t('지금 평가', 'Evaluate now')}</Button>} />
          <div className="space-y-4 p-4">
            <KeyValue items={[
              [<Chip hue="indigo" icon={<Users className="size-3" />}>{t('최소 표본', 'Min sample')}</Chip>, num(r.halt_rules.min_sample)],
              [<Chip hue="rose" icon={<XCircle className="size-3" />}>{t('설치 실패율', 'Install failure rate')}</Chip>, r.halt_rules.max_error_rate != null ? `> ${pct(r.halt_rules.max_error_rate)}` : '—'],
              [<Chip hue="amber" icon={<Undo2 className="size-3" />}>{t('부팅 폴백률', 'Boot fallback rate')}</Chip>, r.halt_rules.max_boot_fallback_rate != null ? `> ${pct(r.halt_rules.max_boot_fallback_rate)}` : '—'],
              [<Chip hue="fuchsia" icon={<Hash className="size-3" />}>{t('오류 코드별', 'Per error code')}</Chip>, Object.keys(r.halt_rules.max_error_code_rate).length
                ? <span className="flex flex-wrap gap-1">{Object.entries(r.halt_rules.max_error_code_rate).map(([c, v]) => (
                  <Badge key={c} hue={hueOf(c)}><span className="font-mono">{c}</span>: &gt; {pct(v)}</Badge>))}</span> : '—'],
              [<Chip hue="orange" icon={<OctagonX className="size-3" />}>{t('중단 시', 'On halt')}</Chip>, r.halt_mode === 'stop_new' ? t('신규 할당만 중단', 'Stop new assignments only') : t('진행 중 기기도 중단', 'Also stop in-progress devices')],
            ]} />
            {evaluation && (
              <div className={`rounded-md border px-3 py-2.5 text-xs ${evaluation.halt ? 'border-critical/30 bg-critical/5' : 'border-good/30 bg-good/5'}`}>
                <p className="font-semibold text-ink">{evaluation.halt ? t('중단 기준 초과', 'Halt threshold exceeded') : t('기준 이내', 'Within thresholds')}</p>
                {evaluation.reasons.map((reason) => <p key={reason} className="mt-0.5 text-ink-2">{reason}</p>)}
                {!evaluation.halt && <p className="mt-0.5 text-muted">{t(`시도 ${evaluation.window.attempted} · 판정 ${evaluation.window.installed}`, `Attempts ${evaluation.window.attempted} · Verdicts ${evaluation.window.installed}`)}</p>}
              </div>
            )}
          </div>
          <div className="border-t border-line p-4">
            <p className="mb-2 flex items-center gap-2 text-xs font-medium text-muted">
              <span aria-hidden className={cx('size-2 rounded-full', HUE.teal.dot)} />{t('기기 정책', 'Device policy')}</p>
            <KeyValue items={[
              [<Chip hue="sky" icon={<Wifi className="size-3" />}>{t('네트워크', 'Network')}</Chip>, r.policy.require_unmetered ? t('비측정 네트워크만', 'Unmetered only') : t('제한 없음', 'Any')],
              [<Chip hue="lime" icon={<BatteryMedium className="size-3" />}>{t('최소 배터리', 'Min battery')}</Chip>, `${r.policy.min_battery_pct}%`],
              [<Chip hue="violet" icon={<RotateCcw className="size-3" />}>{t('최대 시도', 'Max attempts')}</Chip>, t(`${r.policy.max_attempts}회`, `${r.policy.max_attempts}`)],
              [<Chip hue="teal" icon={<Timer className="size-3" />}>{t('체크 주기', 'Check interval')}</Chip>, t(`${Math.round(r.policy.check_interval_s / 3600)}시간 ±10%`, `${Math.round(r.policy.check_interval_s / 3600)}h ±10%`)],
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
              toast({ kind: 'success', title: t(`${ACTION[action].label} 완료`, `${ACTION[action].label} done`) })
              reload()
            } catch (e) {
              toast({ kind: 'error', title: t(`${ACTION[action].label} 실패`, `${ACTION[action].label} failed`), description: (e as Error).message })
              throw e
            }
          }} />
      )}
    </>
  )
}
