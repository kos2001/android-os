import { RefreshCw, Search, Smartphone, Tags, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { PageHeader, StatTile } from '../components/layout'
import { Dialog, useToast } from '../components/ui/overlay'
import { Button, Card, EmptyState, ErrorBanner, Field, Input, KeyValue, Mono, Select, Skeleton } from '../components/ui/primitives'
import { ASSIGNMENT_LABEL, Badge, ChannelBadge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api } from '../lib/api'
import { dateTime, num, relativeTime, shortFingerprint } from '../lib/format'
import { navigate, useAsync, useRoute } from '../lib/hooks'
import { useT } from '../lib/i18n'
import { hueOf } from '../lib/palette'

function DeviceDialog({ hash, onClose, onSaved }: { hash: string; onClose: () => void; onSaved: () => void }) {
  const t = useT()
  const toast = useToast()
  const detail = useAsync(() => api.device(hash), [hash])
  const [tags, setTags] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error>()
  useEffect(() => { if (detail.data) setTags(detail.data.tags.join(', ')) }, [detail.data])
  const d = detail.data
  const save = async () => {
    setBusy(true)
    setError(undefined)
    try {
      await api.setDeviceTags(hash, tags.split(',').map((s) => s.trim()).filter(Boolean))
      toast({ kind: 'success', title: t('기기 태그 저장됨', 'Device tags saved') })
      detail.reload()
      onSaved()
    } catch (e) { setError(e as Error) } finally { setBusy(false) }
  }
  return <Dialog open onClose={onClose} title={t('기기 상세', 'Device details')} width="max-w-2xl"
    description={<span className="break-all">{hash}</span>} footer={<><Button onClick={onClose}>{t('닫기', 'Close')}</Button>
      <Button variant="primary" loading={busy} disabled={!d} onClick={save}>{t('태그 저장', 'Save tags')}</Button></>}>
    {detail.error && <ErrorBanner error={detail.error} onRetry={detail.reload} />}
    {error && <ErrorBanner error={error} />}
    {!d && !detail.error && <Skeleton className="h-48" />}
    {d && <div className="space-y-5">
      <KeyValue items={[
        [t('모델 / 채널', 'Model / channel'), <span className="flex gap-2"><Badge hue={hueOf(d.device)}>{d.device}</Badge><ChannelBadge channel={d.channel} /></span>],
        [t('빌드', 'Build'), <Mono className="break-all">{d.fingerprint}</Mono>],
        [t('보안 패치', 'Security patch'), d.security_patch ?? '—'],
        [t('지역 / 통신사 / SKU', 'Region / carrier / SKU'), [d.region, d.carrier, d.sku].map((v) => v ?? '—').join(' / ')],
        [t('최초 체크인', 'First check-in'), dateTime(d.first_seen_at)],
        [t('최근 체크인', 'Last check-in'), dateTime(d.last_seen_at)],
      ]} />
      <Field label={t('배포 태그', 'Deployment tags')}
        hint={t('쉼표로 구분 · 최대 20개 · 영문·숫자·점·밑줄·하이픈, 태그당 32자. 태그 하나가 일치하면 배포 대상입니다.',
          'Comma separated · up to 20 tags · letters, numbers, dots, underscores, hyphens; 32 characters each. Any matching tag includes the device.')}>
        <Input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="canary, lab-seoul" />
      </Field>
      <Card><DataTable rows={d.assignments} rowKey={(a) => a.id} columns={[
        { key: 'rollout', header: t('롤아웃', 'Rollout'), cell: (a) => <a className="text-accent hover:underline" href={`#/rollouts/${a.rollout_id}`}>#{a.rollout_id}</a> },
        { key: 'state', header: t('설치 상태', 'Install status'), cell: (a) => <Badge hue={hueOf(a.state)}>{ASSIGNMENT_LABEL[a.state]}</Badge> },
        { key: 'attempt', header: t('시도', 'Attempt'), cell: (a) => a.attempt },
        { key: 'updated', header: t('갱신', 'Updated'), cell: (a) => relativeTime(a.updated_at) },
      ]} empty={<p className="p-6 text-center text-muted">{t('배포 이력이 없습니다', 'No deployment history')}</p>} /></Card>
    </div>}
  </Dialog>
}

export default function DevicesPage() {
  const t = useT()
  const { segments } = useRoute()
  const hash = segments[0] === 'devices' && /^[0-9a-f]{64}$/.test(segments[1] ?? '') ? segments[1] : undefined
  const [query, setQuery] = useState('')
  const [q, setQ] = useState('')
  const [model, setModel] = useState('')
  const [channel, setChannel] = useState('')
  const [tag, setTag] = useState('')
  const [recent, setRecent] = useState('')
  const [offset, setOffset] = useState(0)
  const summary = useAsync(() => api.fleetSummary(), [], 30_000)
  const list = useAsync(() => api.devices({ q, device: model, channel, tag, seen_within_hours: recent || undefined,
    limit: '50', offset: String(offset) }), [q, model, channel, tag, recent, offset], 30_000)
  const reload = () => { summary.reload(); list.reload() }
  const change = (set: (v: string) => void, v: string) => { set(v); setOffset(0) }
  const total = list.data?.total ?? 0
  return <>
    <PageHeader title={t('기기 인벤토리', 'Device inventory')}
      description={t('체크인한 기기의 최신 빌드와 보안 패치를 조회하고, 태그로 배포 대상을 묶습니다.',
        'Inspect checked-in devices, their latest builds and security patches, and group deployment targets with tags.')}
      actions={<Button icon={<RefreshCw className="size-4" />} onClick={reload}>{t('새로고침', 'Refresh')}</Button>} />
    <div className="mb-4 grid gap-3 sm:grid-cols-3">
      <StatTile label={t('등록 기기', 'Known devices')} value={summary.data ? num(summary.data.total) : '—'} icon={<Users className="size-4" />} />
      <StatTile label={t('24시간 내 체크인', 'Checked in within 24h')} value={summary.data ? num(summary.data.seen_24h) : '—'} icon={<Smartphone className="size-4" />}
        sub={t('최근 체크인 기준 · 연결 상태를 의미하지 않음', 'Based on last check-in · does not indicate connectivity')} />
      <StatTile label={t('배포 태그', 'Deployment tags')} value={summary.data ? num(summary.data.tags.length) : '—'} icon={<Tags className="size-4" />} />
    </div>
    {(list.error || summary.error) && <div className="mb-4"><ErrorBanner error={(list.error || summary.error)!} onRetry={reload} /></div>}
    <Card>
      <div className="flex flex-wrap gap-3 border-b border-line p-3">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); change(setQ, query.trim()) }}>
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('기기 해시, 모델, 빌드 검색', 'Search device hash, model, build')}
            aria-label={t('기기 검색', 'Search devices')} />
          <Button type="submit" aria-label={t('검색', 'Search')} icon={<Search className="size-4" />} />
        </form>
        <Select aria-label={t('모델 필터', 'Model filter')} value={model} onChange={(e) => change(setModel, e.target.value)} className="w-auto">
          <option value="">{t('모든 모델', 'All models')}</option>
          {summary.data?.models.map((m) => <option key={m.device} value={m.device}>{m.device} ({m.devices})</option>)}
        </Select>
        <Select aria-label={t('채널 필터', 'Channel filter')} value={channel} onChange={(e) => change(setChannel, e.target.value)} className="w-auto">
          <option value="">{t('모든 채널', 'All channels')}</option>{['testing', 'beta', 'stable'].map((c) => <option key={c}>{c}</option>)}
        </Select>
        <Select aria-label={t('태그 필터', 'Tag filter')} value={tag} onChange={(e) => change(setTag, e.target.value)} className="w-auto">
          <option value="">{t('모든 태그', 'All tags')}</option>
          {summary.data?.tags.map((g) => <option key={g.tag} value={g.tag}>{g.tag} ({g.devices})</option>)}
        </Select>
        <Select aria-label={t('체크인 필터', 'Check-in filter')} value={recent} onChange={(e) => change(setRecent, e.target.value)} className="w-auto">
          <option value="">{t('모든 체크인', 'All check-ins')}</option><option value="24">{t('최근 24시간', 'Last 24h')}</option>
          <option value="168">{t('최근 7일', 'Last 7 days')}</option>
        </Select>
      </div>
      <DataTable rows={list.data?.items} loading={list.loading} rowKey={(d) => d.device_hash}
        onRowClick={(d) => navigate(`/devices/${d.device_hash}`)} columns={[
          { key: 'hash', header: t('기기', 'Device'), cell: (d) => <Mono>{d.device_hash.slice(0, 12)}…</Mono> },
          { key: 'model', header: t('모델', 'Model'), cell: (d) => <Badge hue={hueOf(d.device)}>{d.device}</Badge> },
          { key: 'channel', header: t('채널', 'Channel'), cell: (d) => <ChannelBadge channel={d.channel} /> },
          { key: 'build', header: t('현재 빌드', 'Current build'), cell: (d) => <span title={d.fingerprint}>{shortFingerprint(d.fingerprint)}</span> },
          { key: 'patch', header: t('보안 패치', 'Security patch'), cell: (d) => d.security_patch ?? '—' },
          { key: 'tags', header: t('태그', 'Tags'), cell: (d) => <span className="flex flex-wrap gap-1">{d.tags.map((g) => <Badge key={g} hue={hueOf(g)}>{g}</Badge>)}</span> },
          { key: 'seen', header: t('최근 체크인', 'Last check-in'), cell: (d) => <span title={dateTime(d.last_seen_at)}>{relativeTime(d.last_seen_at)}</span> },
        ]} empty={<EmptyState icon={<Smartphone className="size-5" />} title={t('기기가 없습니다', 'No devices')}
          description={t('기기의 update-check 요청이 들어오면 자동으로 등록됩니다. 필터가 있다면 조건을 확인하세요.',
            'Devices are registered automatically on update checks. Review your filters if no devices appear.')} />} />
      <div className="flex items-center justify-between border-t border-line p-3 text-xs text-muted">
        <span>{total ? `${offset + 1}–${Math.min(offset + 50, total)} / ${num(total)}` : '0 / 0'}</span>
        <div className="flex gap-2"><Button size="sm" disabled={offset === 0} onClick={() => setOffset((v) => Math.max(0, v - 50))}>{t('이전', 'Previous')}</Button>
          <Button size="sm" disabled={offset + 50 >= total} onClick={() => setOffset((v) => v + 50)}>{t('다음', 'Next')}</Button></div>
      </div>
    </Card>
    {hash && <DeviceDialog key={hash} hash={hash} onClose={() => navigate('/devices')} onSaved={reload} />}
  </>
}
