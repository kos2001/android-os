import { CheckCircle2, CircleDashed, GitCompareArrows, Smartphone } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { BarList } from '../components/charts/charts'
import { PageHeader, StatTile } from '../components/layout'
import { Card, cx, EmptyState, ErrorBanner, Field, Mono, Segmented, Select, Skeleton } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api } from '../lib/api'
import { num, parseFingerprint, pct, shortFingerprint } from '../lib/format'
import { useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'
import { HUE, hueOf } from '../lib/palette'

/** 빌드 fingerprint 의 기기·릴리스를 색 칩으로 (장식용: 같은 기기·릴리스는 항상 같은 색). */
function BuildChips({ fingerprint }: { fingerprint: string }) {
  const f = parseFingerprint(fingerprint)
  if (!f.device) return null
  const h = HUE[hueOf(f.device)]
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span className={cx('inline-flex h-5 items-center gap-1 rounded-full pl-0.5 pr-2 text-[11px] font-medium ring-1 ring-inset', h.soft, h.text, h.ring)}>
        <span aria-hidden className={cx('flex size-4 items-center justify-center rounded-full text-white', h.solid)}><Smartphone className="size-2.5" /></span>
        {f.device}
      </span>
      {f.release && <Badge hue={hueOf(`android-${f.release}`)}>Android {f.release}</Badge>}
      <Badge hue={hueOf(f.buildId)} className="font-mono">{f.buildId}</Badge>
    </span>
  )
}

export default function DeltaPage() {
  const t = useT()
  const packages = useAsync(() => api.packages(), [])
  const targets = useMemo(() => [...new Set((packages.data ?? []).filter((p) => p.status === 'ready').map((p) => p.post_build))],
    [packages.data])
  const [target, setTarget] = useState('')
  const [days, setDays] = useState<'7' | '14' | '30'>('14')
  useEffect(() => { if (!target && targets[0]) setTarget(targets[0]) }, [targets, target])
  const report = useAsync(() => (target ? api.deltaCandidates(target, Number(days)) : Promise.resolve(undefined)), [target, days])
  const d = report.data
  const uncovered = d ? d.sources.filter((s) => !s.has_incremental) : []
  const coveredDevices = d ? d.sources.filter((s) => s.has_incremental).reduce((a, s) => a + s.devices, 0) : 0

  return (
    <>
      <PageHeader title={t('Delta 후보', 'Delta candidates')}
        description={t('대상 빌드로 가야 하는 활성 기기가 지금 어느 source 빌드에 있는지 봅니다. incremental 이 없는 source 는 full 패키지(수 GB)를 받습니다.', 'Shows which source builds the active devices bound for the target build are on now. Sources without an incremental receive the full package (several GB).')} />
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3 p-4">
          <Field label={t('대상 빌드', 'Target build')} className="min-w-80 flex-1">
            <Select value={target} onChange={(e) => setTarget(e.target.value)} className="font-mono text-xs">
              {targets.length === 0 && <option value="">{t('Ready 패키지 없음', 'No Ready packages')}</option>}
              {targets.map((fp) => <option key={fp} value={fp}>{shortFingerprint(fp)}</option>)}
            </Select>
            {target && <span className="mt-1.5 block"><BuildChips fingerprint={target} /></span>}
          </Field>
          <Field label={t('체크인 기간', 'Check-in window')}>
            <Segmented value={days} onChange={setDays} items={[{ value: '7', label: t('7일', '7 days') }, { value: '14', label: t('14일', '14 days') }, { value: '30', label: t('30일', '30 days') }]} />
          </Field>
        </div>
      </Card>
      {report.error && <ErrorBanner error={report.error} onRetry={report.reload} />}
      {!target ? (
        <Card><EmptyState icon={<GitCompareArrows className="size-5" />} title={t('대상 빌드가 없습니다', 'No target builds')} description={t('먼저 Ready 패키지를 등록하세요.', 'Register a Ready package first.')} /></Card>
      ) : !d ? <Skeleton className="h-72" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatTile hue="cyan" label={t('대상 미도달 기기', 'Devices not on target')} value={num(d.active_devices_not_on_target)} sub={t(`최근 ${d.window_days}일 체크인 기준`, `Based on check-ins in the last ${d.window_days} days`)} />
            <StatTile hue="emerald" label={t('incremental 로 커버', 'Covered by incremental')} value={pct(d.active_devices_not_on_target ? coveredDevices / d.active_devices_not_on_target : null)}
              sub={t(`${num(coveredDevices)}대`, `${num(coveredDevices)} devices`)} />
            <StatTile hue="orange" label={t('생성 권장 incremental', 'Incrementals to build')} value={num(uncovered.length)} sub={t('full 로만 갈 수 있는 source 빌드', 'Source builds that can only take a full')} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <div className="p-4">
                <BarList title={t('source 빌드별 기기 수', 'Devices by source build')} subtitle={t('기기별 최신 체크인 기준', 'Based on each device\'s latest check-in')} valueLabel={t('기기 수', 'Devices')}
                  items={d.sources.slice(0, 10).map((s) => ({
                    key: s.fingerprint, value: s.devices, hint: `${pct(s.share)} · ${s.has_incremental ? t('incremental 있음', 'Has incremental') : t('full 만 가능', 'Full only')}`,
                    label: shortFingerprint(s.fingerprint),
                  }))}
                  empty={<p className="py-8 text-center text-xs text-muted">{t('최근 체크인한 기기가 없습니다', 'No recent device check-ins')}</p>} />
              </div>
            </Card>
            <Card>
              <DataTable rows={d.sources} rowKey={(s) => s.fingerprint}
                empty={<p className="py-8 text-center text-xs text-muted">{t('최근 체크인한 기기가 없습니다', 'No recent device check-ins')}</p>}
                initialSort={{ key: 'devices', dir: 'desc' }}
                columns={[
                  { key: 'fp', header: t('Source 빌드', 'Source build'), cell: (s) => (
                    <div className="space-y-1">
                      <BuildChips fingerprint={s.fingerprint} />
                      <Mono className="block break-all text-muted">{s.fingerprint}</Mono>
                    </div>
                  ) },
                  { key: 'devices', header: t('기기', 'Devices'), align: 'right', sort: (s) => s.devices, cell: (s) => num(s.devices) },
                  { key: 'share', header: t('비중', 'Share'), align: 'right', sort: (s) => s.share, cell: (s) => pct(s.share) },
                  { key: 'inc', header: 'incremental', cell: (s) => s.has_incremental
                    ? <Badge tone="good" icon={<CheckCircle2 className="size-3" />}>{t('있음', 'Available')}</Badge>
                    : <Badge tone="warning" icon={<CircleDashed className="size-3" />}>{t('생성 권장', 'Recommended')}</Badge> },
                ]} />
            </Card>
          </div>
        </div>
      )}
    </>
  )
}
