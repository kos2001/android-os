import { CheckCircle2, CircleDashed, GitCompareArrows } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { BarList } from '../components/charts/charts'
import { PageHeader, StatTile } from '../components/layout'
import { Card, EmptyState, ErrorBanner, Field, Mono, Segmented, Select, Skeleton } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api } from '../lib/api'
import { num, pct, shortFingerprint } from '../lib/format'
import { useAsync } from '../lib/hooks'

export default function DeltaPage() {
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
      <PageHeader title="Delta 후보"
        description="대상 빌드로 가야 하는 활성 기기가 지금 어느 source 빌드에 있는지 봅니다. incremental 이 없는 source 는 full 패키지(수 GB)를 받습니다." />
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3 p-4">
          <Field label="대상 빌드" className="min-w-80 flex-1">
            <Select value={target} onChange={(e) => setTarget(e.target.value)} className="font-mono text-xs">
              {targets.length === 0 && <option value="">Ready 패키지 없음</option>}
              {targets.map((t) => <option key={t} value={t}>{shortFingerprint(t)}</option>)}
            </Select>
          </Field>
          <Field label="체크인 기간">
            <Segmented value={days} onChange={setDays} items={[{ value: '7', label: '7일' }, { value: '14', label: '14일' }, { value: '30', label: '30일' }]} />
          </Field>
        </div>
      </Card>
      {report.error && <ErrorBanner error={report.error} onRetry={report.reload} />}
      {!target ? (
        <Card><EmptyState icon={<GitCompareArrows className="size-5" />} title="대상 빌드가 없습니다" description="먼저 Ready 패키지를 등록하세요." /></Card>
      ) : !d ? <Skeleton className="h-72" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatTile label="대상 미도달 기기" value={num(d.active_devices_not_on_target)} sub={`최근 ${d.window_days}일 체크인 기준`} />
            <StatTile label="incremental 로 커버" value={pct(d.active_devices_not_on_target ? coveredDevices / d.active_devices_not_on_target : null)}
              sub={`${num(coveredDevices)}대`} />
            <StatTile label="생성 권장 incremental" value={num(uncovered.length)} sub="full 로만 갈 수 있는 source 빌드" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <div className="p-4">
                <BarList title="source 빌드별 기기 수" subtitle="기기별 최신 체크인 기준" valueLabel="기기 수"
                  items={d.sources.slice(0, 10).map((s) => ({
                    key: s.fingerprint, value: s.devices, hint: `${pct(s.share)} · ${s.has_incremental ? 'incremental 있음' : 'full 만 가능'}`,
                    label: shortFingerprint(s.fingerprint),
                  }))}
                  empty={<p className="py-8 text-center text-xs text-muted">최근 체크인한 기기가 없습니다</p>} />
              </div>
            </Card>
            <Card>
              <DataTable rows={d.sources} rowKey={(s) => s.fingerprint}
                empty={<p className="py-8 text-center text-xs text-muted">최근 체크인한 기기가 없습니다</p>}
                initialSort={{ key: 'devices', dir: 'desc' }}
                columns={[
                  { key: 'fp', header: 'Source 빌드', cell: (s) => <Mono className="break-all">{s.fingerprint}</Mono> },
                  { key: 'devices', header: '기기', align: 'right', sort: (s) => s.devices, cell: (s) => num(s.devices) },
                  { key: 'share', header: '비중', align: 'right', sort: (s) => s.share, cell: (s) => pct(s.share) },
                  { key: 'inc', header: 'incremental', cell: (s) => s.has_incremental
                    ? <Badge tone="good" icon={<CheckCircle2 className="size-3" />}>있음</Badge>
                    : <Badge tone="warning" icon={<CircleDashed className="size-3" />}>생성 권장</Badge> },
                ]} />
            </Card>
          </div>
        </div>
      )}
    </>
  )
}
