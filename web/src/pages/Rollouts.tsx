import { Plus, Rocket, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { PageHeader } from '../components/layout'
import { Dialog, useToast } from '../components/ui/overlay'
import { Button, Card, EmptyState, ErrorBanner, Field, Input, Segmented, Select, Switch } from '../components/ui/primitives'
import { ChannelBadge, RolloutBadge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api, type Channel, type RolloutState } from '../lib/api'
import { relativeTime, shortFingerprint } from '../lib/format'
import { navigate, useAsync } from '../lib/hooks'

interface StageForm { percent: string; min_soak_hours: string }

const DEFAULT_STAGES: StageForm[] = [
  { percent: '1', min_soak_hours: '24' }, { percent: '10', min_soak_hours: '24' },
  { percent: '50', min_soak_hours: '24' }, { percent: '100', min_soak_hours: '0' },
]

function StageBar({ stages, current }: { stages: { percent: number }[]; current: number }) {
  return (
    <div className="flex items-center gap-[2px]" aria-label={`단계 ${current}/${stages.length}`}>
      {stages.map((s, i) => (
        <span key={i} title={`${i + 1}단계 ${s.percent}%`}
          className={`h-1.5 w-5 first:rounded-l-full last:rounded-r-full ${i < current ? 'bg-accent' : 'bg-line'}`} />
      ))}
    </div>
  )
}

function CreateRolloutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast()
  const packages = useAsync(() => api.packages(), [open])
  const targets = useMemo(() => {
    const ready = (packages.data ?? []).filter((p) => p.status === 'ready')
    return [...new Map(ready.map((p) => [p.post_build, p])).values()]
  }, [packages.data])

  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [channel, setChannel] = useState<Channel>('testing')
  const [stages, setStages] = useState<StageForm[]>(DEFAULT_STAGES)
  const [minSample, setMinSample] = useState('200')
  const [maxError, setMaxError] = useState('3')
  const [maxFallback, setMaxFallback] = useState('0.5')
  const [haltMode, setHaltMode] = useState<'stop_new' | 'stop_all_pending'>('stop_new')
  const [unmetered, setUnmetered] = useState(true)
  const [battery, setBattery] = useState('30')
  const [maxAttempts, setMaxAttempts] = useState('2')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error>()

  useEffect(() => {
    if (!open) return
    setError(undefined)
    setStages(DEFAULT_STAGES)
    setName('')
  }, [open])
  useEffect(() => { if (!target && targets[0]) setTarget(targets[0].post_build) }, [targets, target])

  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      const r = await api.createRollout({
        name, target_fingerprint: target, channel,
        stages: stages.map((s) => ({ percent: Number(s.percent), min_soak_hours: Number(s.min_soak_hours) })),
        halt_rules: {
          min_sample: Number(minSample),
          max_error_rate: maxError ? Number(maxError) / 100 : null,
          max_boot_fallback_rate: maxFallback ? Number(maxFallback) / 100 : null,
        },
        halt_mode: haltMode,
        policy: { require_unmetered: unmetered, min_battery_pct: Number(battery), max_attempts: Number(maxAttempts) },
      })
      toast({ kind: 'success', title: `롤아웃 ${r.name} 생성됨`, description: '초안 상태입니다. 시작하면 기기에 제공됩니다.' })
      onClose()
      navigate(`/rollouts/${r.id}`)
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }

  const setStage = (i: number, k: keyof StageForm, v: string) =>
    setStages((s) => s.map((st, j) => (j === i ? { ...st, [k]: v.replace(/[^\d.]/g, '') } : st)))

  return (
    <Dialog open={open} onClose={onClose} title="롤아웃 생성" width="max-w-2xl"
      description="단계별 비율로 기기에 배포합니다. 기기는 안정적 해시로 배정되어 비율을 올려도 기존 대상이 유지됩니다."
      footer={<><Button onClick={onClose}>취소</Button>
        <Button variant="primary" loading={busy} disabled={!name || !target} onClick={submit}>초안 생성</Button></>}>
      <div className="space-y-5">
        {error && <ErrorBanner error={error} />}
        <div className="grid grid-cols-2 gap-3">
          <Field label="이름"><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="lynx-17-jul" /></Field>
          <Field label="채널">
            <Segmented value={channel} onChange={setChannel} items={[
              { value: 'testing', label: 'testing' }, { value: 'beta', label: 'beta' }, { value: 'stable', label: 'stable' }]} />
          </Field>
          <Field label="대상 빌드" className="col-span-2" hint={targets.length ? undefined : 'Ready 패키지가 있어야 롤아웃을 만들 수 있습니다'}>
            <Select value={target} onChange={(e) => setTarget(e.target.value)} className="font-mono text-xs">
              {targets.map((p) => <option key={p.post_build} value={p.post_build}>{shortFingerprint(p.post_build)}</option>)}
            </Select>
          </Field>
        </div>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-medium text-ink-2">단계</h3>
            <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} disabled={stages.length >= 8}
              onClick={() => setStages((s) => [...s, { percent: '100', min_soak_hours: '0' }])}>단계 추가</Button>
          </div>
          <div className="space-y-2">
            {stages.map((s, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-12 text-xs text-muted">{i + 1}단계</span>
                <Input value={s.percent} onChange={(e) => setStage(i, 'percent', e.target.value)} className="w-24 text-right" aria-label="비율" />
                <span className="text-xs text-muted">% · 최소 유지</span>
                <Input value={s.min_soak_hours} onChange={(e) => setStage(i, 'min_soak_hours', e.target.value)} className="w-20 text-right" aria-label="유지 시간" />
                <span className="text-xs text-muted">시간</span>
                <Button size="sm" variant="ghost" aria-label="삭제" disabled={stages.length <= 1}
                  onClick={() => setStages((st) => st.filter((_, j) => j !== i))} icon={<Trash2 className="size-3.5" />} />
              </div>
            ))}
          </div>
        </section>

        <div className="grid gap-4 md:grid-cols-2">
          <section className="space-y-3 rounded-lg border border-line p-3">
            <h3 className="text-xs font-medium text-ink-2">자동 중단</h3>
            <div className="grid grid-cols-3 gap-2">
              <Field label="최소 표본"><Input value={minSample} onChange={(e) => setMinSample(e.target.value.replace(/\D/g, ''))} /></Field>
              <Field label="설치 실패율 %"><Input value={maxError} onChange={(e) => setMaxError(e.target.value)} /></Field>
              <Field label="부팅 폴백률 %"><Input value={maxFallback} onChange={(e) => setMaxFallback(e.target.value)} /></Field>
            </div>
            <Field label="중단 시 동작">
              <Select value={haltMode} onChange={(e) => setHaltMode(e.target.value as typeof haltMode)}>
                <option value="stop_new">신규 할당만 중단 (진행 중 기기는 계속)</option>
                <option value="stop_all_pending">진행 중 기기에도 제공 중단</option>
              </Select>
            </Field>
          </section>
          <section className="space-y-2 rounded-lg border border-line p-3">
            <h3 className="text-xs font-medium text-ink-2">기기 정책</h3>
            <Switch label="비측정 네트워크에서만" checked={unmetered} onChange={setUnmetered} />
            <div className="grid grid-cols-2 gap-2">
              <Field label="최소 배터리 %"><Input value={battery} onChange={(e) => setBattery(e.target.value.replace(/\D/g, ''))} /></Field>
              <Field label="최대 시도 횟수"><Input value={maxAttempts} onChange={(e) => setMaxAttempts(e.target.value.replace(/\D/g, ''))} /></Field>
            </div>
          </section>
        </div>
      </div>
    </Dialog>
  )
}

export default function RolloutsPage() {
  const list = useAsync(() => api.rollouts(), [], 15_000)
  const [state, setState] = useState<'all' | RolloutState>('all')
  const [open, setOpen] = useState(false)
  const rows = list.data?.filter((r) => state === 'all' || r.state === state)
  const count = (s: RolloutState) => list.data?.filter((r) => r.state === s).length ?? 0

  return (
    <>
      <PageHeader title="롤아웃" description="대상 빌드를 단계적으로 배포하고 설치 결과에 따라 자동으로 중단합니다."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>롤아웃 생성</Button>} />
      {list.error && <div className="mb-4"><ErrorBanner error={list.error} onRetry={list.reload} /></div>}
      <Card>
        <DataTable
          rows={rows}
          loading={list.loading}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(`/rollouts/${r.id}`)}
          searchText={(r) => `${r.name} ${r.device} ${r.target_fingerprint}`}
          searchPlaceholder="이름, 기기, 빌드 검색"
          initialSort={{ key: 'created', dir: 'desc' }}
          toolbar={<Segmented value={state} onChange={setState} items={[
            { value: 'all', label: `전체 ${list.data?.length ?? 0}` }, { value: 'active', label: `진행 중 ${count('active')}` },
            { value: 'halted', label: `중단 ${count('halted')}` }, { value: 'draft', label: `초안 ${count('draft')}` },
          ]} />}
          empty={<EmptyState icon={<Rocket className="size-5" />} title="롤아웃이 없습니다"
            description="Ready 패키지를 등록한 뒤 대상 빌드로 롤아웃을 만드세요."
            action={<Button variant="primary" onClick={() => setOpen(true)}>롤아웃 생성</Button>} />}
          columns={[
            { key: 'state', header: '상태', sort: (r) => r.state, cell: (r) => <RolloutBadge state={r.state} /> },
            { key: 'name', header: '이름', sort: (r) => r.name, cell: (r) => <span className="font-medium">{r.name}</span> },
            { key: 'target', header: '대상', cell: (r) => <span className="text-ink-2">{shortFingerprint(r.target_fingerprint)}</span> },
            { key: 'channel', header: '채널', sort: (r) => r.channel, cell: (r) => <ChannelBadge channel={r.channel} /> },
            { key: 'progress', header: '진행', sort: (r) => r.current_percent, cell: (r) => (
              <div className="flex items-center gap-3">
                <StageBar stages={r.stages} current={r.current_stage} />
                <span className="tabular text-xs text-ink">{r.current_percent}%</span>
              </div>) },
            { key: 'created', header: '생성', align: 'right', sort: (r) => r.created_at,
              cell: (r) => <span className="text-muted">{relativeTime(r.created_at)}</span> },
          ]}
        />
      </Card>
      <CreateRolloutDialog open={open} onClose={() => { setOpen(false); list.reload() }} />
    </>
  )
}
