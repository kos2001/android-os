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
import { useT } from '../lib/i18n'

interface StageForm { percent: string; min_soak_hours: string }

const DEFAULT_STAGES: StageForm[] = [
  { percent: '1', min_soak_hours: '24' }, { percent: '10', min_soak_hours: '24' },
  { percent: '50', min_soak_hours: '24' }, { percent: '100', min_soak_hours: '0' },
]

function StageBar({ stages, current }: { stages: { percent: number }[]; current: number }) {
  const t = useT()
  return (
    <div className="flex items-center gap-[2px]" aria-label={t(`단계 ${current}/${stages.length}`, `Stage ${current}/${stages.length}`)}>
      {stages.map((s, i) => (
        <span key={i} title={t(`${i + 1}단계 ${s.percent}%`, `Stage ${i + 1} ${s.percent}%`)}
          className={`h-1.5 w-5 first:rounded-l-full last:rounded-r-full ${i < current ? 'bg-accent' : 'bg-line'}`} />
      ))}
    </div>
  )
}

function CreateRolloutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT()
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
      toast({ kind: 'success', title: t(`롤아웃 ${r.name} 생성됨`, `Rollout ${r.name} created`), description: t('초안 상태입니다. 시작하면 기기에 제공됩니다.', 'It is a draft. Start it to offer the update to devices.') })
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
    <Dialog open={open} onClose={onClose} title={t('롤아웃 생성', 'Create rollout')} width="max-w-2xl"
      description={t('단계별 비율로 기기에 배포합니다. 기기는 안정적 해시로 배정되어 비율을 올려도 기존 대상이 유지됩니다.', 'Deploys to devices in percentage stages. Devices are assigned by a stable hash, so existing targets stay in when the percentage rises.')}
      footer={<><Button onClick={onClose}>{t('취소', 'Cancel')}</Button>
        <Button variant="primary" loading={busy} disabled={!name || !target} onClick={submit}>{t('초안 생성', 'Create draft')}</Button></>}>
      <div className="space-y-5">
        {error && <ErrorBanner error={error} />}
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('이름', 'Name')}><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="lynx-17-jul" /></Field>
          <Field label={t('채널', 'Channel')}>
            <Segmented value={channel} onChange={setChannel} items={[
              { value: 'testing', label: 'testing' }, { value: 'beta', label: 'beta' }, { value: 'stable', label: 'stable' }]} />
          </Field>
          <Field label={t('대상 빌드', 'Target build')} className="col-span-2" hint={targets.length ? undefined : t('Ready 패키지가 있어야 롤아웃을 만들 수 있습니다', 'A Ready package is required to create a rollout')}>
            <Select value={target} onChange={(e) => setTarget(e.target.value)} className="font-mono text-xs">
              {targets.map((p) => <option key={p.post_build} value={p.post_build}>{shortFingerprint(p.post_build)}</option>)}
            </Select>
          </Field>
        </div>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-medium text-ink-2">{t('단계', 'Stages')}</h3>
            <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} disabled={stages.length >= 8}
              onClick={() => setStages((s) => [...s, { percent: '100', min_soak_hours: '0' }])}>{t('단계 추가', 'Add stage')}</Button>
          </div>
          <div className="space-y-2">
            {stages.map((s, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-12 text-xs text-muted">{t(`${i + 1}단계`, `Stage ${i + 1}`)}</span>
                <Input value={s.percent} onChange={(e) => setStage(i, 'percent', e.target.value)} className="w-24 text-right" aria-label={t('비율', 'Percentage')} />
                <span className="text-xs text-muted">{t('% · 최소 유지', '% · min soak')}</span>
                <Input value={s.min_soak_hours} onChange={(e) => setStage(i, 'min_soak_hours', e.target.value)} className="w-20 text-right" aria-label={t('유지 시간', 'Soak hours')} />
                <span className="text-xs text-muted">{t('시간', 'hours')}</span>
                <Button size="sm" variant="ghost" aria-label={t('삭제', 'Delete')} disabled={stages.length <= 1}
                  onClick={() => setStages((st) => st.filter((_, j) => j !== i))} icon={<Trash2 className="size-3.5" />} />
              </div>
            ))}
          </div>
        </section>

        <div className="grid gap-4 md:grid-cols-2">
          <section className="space-y-3 rounded-lg border border-line p-3">
            <h3 className="text-xs font-medium text-ink-2">{t('자동 중단', 'Auto-halt')}</h3>
            <div className="grid grid-cols-3 gap-2">
              <Field label={t('최소 표본', 'Min sample')}><Input value={minSample} onChange={(e) => setMinSample(e.target.value.replace(/\D/g, ''))} /></Field>
              <Field label={t('설치 실패율 %', 'Install failure rate %')}><Input value={maxError} onChange={(e) => setMaxError(e.target.value)} /></Field>
              <Field label={t('부팅 폴백률 %', 'Boot fallback rate %')}><Input value={maxFallback} onChange={(e) => setMaxFallback(e.target.value)} /></Field>
            </div>
            <Field label={t('중단 시 동작', 'On halt')}>
              <Select value={haltMode} onChange={(e) => setHaltMode(e.target.value as typeof haltMode)}>
                <option value="stop_new">{t('신규 할당만 중단 (진행 중 기기는 계속)', 'Stop new assignments only (in-progress devices continue)')}</option>
                <option value="stop_all_pending">{t('진행 중 기기에도 제공 중단', 'Also stop offering to in-progress devices')}</option>
              </Select>
            </Field>
          </section>
          <section className="space-y-2 rounded-lg border border-line p-3">
            <h3 className="text-xs font-medium text-ink-2">{t('기기 정책', 'Device policy')}</h3>
            <Switch label={t('비측정 네트워크에서만', 'Unmetered networks only')} checked={unmetered} onChange={setUnmetered} />
            <div className="grid grid-cols-2 gap-2">
              <Field label={t('최소 배터리 %', 'Min battery %')}><Input value={battery} onChange={(e) => setBattery(e.target.value.replace(/\D/g, ''))} /></Field>
              <Field label={t('최대 시도 횟수', 'Max attempts')}><Input value={maxAttempts} onChange={(e) => setMaxAttempts(e.target.value.replace(/\D/g, ''))} /></Field>
            </div>
          </section>
        </div>
      </div>
    </Dialog>
  )
}

export default function RolloutsPage() {
  const t = useT()
  const list = useAsync(() => api.rollouts(), [], 15_000)
  const [state, setState] = useState<'all' | RolloutState>('all')
  const [open, setOpen] = useState(false)
  const rows = list.data?.filter((r) => state === 'all' || r.state === state)
  const count = (s: RolloutState) => list.data?.filter((r) => r.state === s).length ?? 0

  return (
    <>
      <PageHeader title={t('롤아웃', 'Rollouts')} description={t('대상 빌드를 단계적으로 배포하고 설치 결과에 따라 자동으로 중단합니다.', 'Roll out target builds in stages and halt automatically based on install results.')}
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>{t('롤아웃 생성', 'Create rollout')}</Button>} />
      {list.error && <div className="mb-4"><ErrorBanner error={list.error} onRetry={list.reload} /></div>}
      <Card>
        <DataTable
          rows={rows}
          loading={list.loading}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(`/rollouts/${r.id}`)}
          searchText={(r) => `${r.name} ${r.device} ${r.target_fingerprint}`}
          searchPlaceholder={t('이름, 기기, 빌드 검색', 'Search name, device, build')}
          initialSort={{ key: 'created', dir: 'desc' }}
          toolbar={<Segmented value={state} onChange={setState} items={[
            { value: 'all', label: t(`전체 ${list.data?.length ?? 0}`, `All ${list.data?.length ?? 0}`) }, { value: 'active', label: t(`진행 중 ${count('active')}`, `Active ${count('active')}`) },
            { value: 'halted', label: t(`중단 ${count('halted')}`, `Halted ${count('halted')}`) }, { value: 'draft', label: t(`초안 ${count('draft')}`, `Draft ${count('draft')}`) },
          ]} />}
          empty={<EmptyState icon={<Rocket className="size-5" />} title={t('롤아웃이 없습니다', 'No rollouts')}
            description={t('Ready 패키지를 등록한 뒤 대상 빌드로 롤아웃을 만드세요.', 'Register a Ready package, then create a rollout for its target build.')}
            action={<Button variant="primary" onClick={() => setOpen(true)}>{t('롤아웃 생성', 'Create rollout')}</Button>} />}
          columns={[
            { key: 'state', header: t('상태', 'Status'), sort: (r) => r.state, cell: (r) => <RolloutBadge state={r.state} /> },
            { key: 'name', header: t('이름', 'Name'), sort: (r) => r.name, cell: (r) => <span className="font-medium">{r.name}</span> },
            { key: 'target', header: t('대상', 'Target'), cell: (r) => <span className="text-ink-2">{shortFingerprint(r.target_fingerprint)}</span> },
            { key: 'channel', header: t('채널', 'Channel'), sort: (r) => r.channel, cell: (r) => <ChannelBadge channel={r.channel} /> },
            { key: 'progress', header: t('진행', 'Progress'), sort: (r) => r.current_percent, cell: (r) => (
              <div className="flex items-center gap-3">
                <StageBar stages={r.stages} current={r.current_stage} />
                <span className="tabular text-xs text-ink">{r.current_percent}%</span>
              </div>) },
            { key: 'created', header: t('생성', 'Created'), align: 'right', sort: (r) => r.created_at,
              cell: (r) => <span className="text-muted">{relativeTime(r.created_at)}</span> },
          ]}
        />
      </Card>
      <CreateRolloutDialog open={open} onClose={() => { setOpen(false); list.reload() }} />
    </>
  )
}
