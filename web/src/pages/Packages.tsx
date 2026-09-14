import { Archive, Boxes, Plus, ScanSearch } from 'lucide-react'
import { useEffect, useState } from 'react'
import { PageHeader } from '../components/layout'
import { ConfirmDialog, Dialog, Drawer, useToast } from '../components/ui/overlay'
import { Button, Card, CopyButton, EmptyState, ErrorBanner, Field, Input, KeyValue, Mono, Segmented } from '../components/ui/primitives'
import { Badge, PackageBadge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api, type InspectResult, type OtaPackage } from '../lib/api'
import { bytes, dateTime, num, relativeTime, shortFingerprint } from '../lib/format'
import { useAsync } from '../lib/hooks'

function RegisterDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [url, setUrl] = useState('')
  const [sha, setSha] = useState('')
  const [inspect, setInspect] = useState<InspectResult>()
  const [error, setError] = useState<Error>()
  const [busy, setBusy] = useState<'inspect' | 'register'>()
  useEffect(() => { if (open) { setUrl(''); setSha(''); setInspect(undefined); setError(undefined) } }, [open])

  const run = async (kind: 'inspect' | 'register') => {
    setBusy(kind)
    setError(undefined)
    try {
      if (kind === 'inspect') {
        setInspect(await api.inspectPackage(url.trim()))
      } else {
        const p = await api.registerPackage(url.trim(), sha.trim() || undefined)
        toast({ kind: p.status === 'ready' ? 'success' : 'warning', title: `패키지 ${p.status === 'ready' ? '등록됨' : '거부됨'}`,
          description: p.status === 'ready' ? shortFingerprint(p.post_build) : p.reject_reasons.join('\n') })
        onDone()
      }
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(undefined)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="OTA 패키지 등록" width="max-w-2xl"
      description="서명된 A/B OTA zip 의 https URL. 서버가 HTTP Range 로 메타데이터만 읽어 검증합니다 (전체 다운로드 없음)."
      footer={<>
        <Button onClick={onClose}>취소</Button>
        <Button icon={<ScanSearch className="size-3.5" />} loading={busy === 'inspect'} disabled={!url.trim()} onClick={() => run('inspect')}>검사만</Button>
        <Button variant="primary" loading={busy === 'register'} disabled={!url.trim()} onClick={() => run('register')}>등록</Button>
      </>}>
      <div className="space-y-3">
        <Field label="패키지 URL" hint="오리진은 ANDROID_OS_PACKAGE_HOSTS 에 있어야 하며 Range 요청과 리다이렉트 없는 응답이 필요합니다">
          <Input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} className="font-mono text-xs"
            placeholder="https://dl.google.com/dl/android/aosp/lynx-ota-cp2a.260705.006-f4d6d546.zip" />
        </Field>
        <Field label="SHA-256 (선택)" hint="빌드 파이프라인이 계산한 값. 서버는 전체 해시를 계산하지 않습니다">
          <Input value={sha} onChange={(e) => setSha(e.target.value.toLowerCase())} className="font-mono text-xs" />
        </Field>
        {error && <ErrorBanner error={error} />}
        {inspect && (
          <div className="rounded-lg border border-line bg-page p-4">
            <div className="mb-3 flex items-center gap-2">
              <PackageBadge status={inspect.ready ? 'ready' : 'rejected'} />
              <Badge>{inspect.package_type}</Badge>
              {inspect.range_requests != null && (
                <span className="text-xs text-muted">Range 요청 {inspect.range_requests}회 · {bytes(inspect.bytes_fetched)} 읽음 / {bytes(inspect.file_size)}</span>
              )}
            </div>
            <KeyValue items={[
              ['대상 빌드', <Mono>{inspect.post_build}</Mono>],
              ['기기', inspect.pre_device.join(', ')],
              ['보안 패치', inspect.post_spl],
              ['SDK', inspect.post_sdk_level ?? '—'],
              ['Source 빌드', inspect.pre_builds.length ? inspect.pre_builds.map((b) => <Mono key={b} className="block">{b}</Mono>) : '— (full)'],
              ['payload', `offset ${num(inspect.payload_offset)} · size ${bytes(inspect.payload_size)}`],
            ]} />
            {inspect.reject_reasons.length > 0 && (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-critical">
                {inspect.reject_reasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>
    </Dialog>
  )
}

export default function PackagesPage() {
  const toast = useToast()
  const list = useAsync(() => api.packages(), [])
  const [status, setStatus] = useState<'all' | OtaPackage['status']>('all')
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<OtaPackage | null>(null)
  const [retire, setRetire] = useState<OtaPackage | null>(null)

  const rows = list.data?.filter((p) => status === 'all' || p.status === status)
  const counts = (s: OtaPackage['status']) => list.data?.filter((p) => p.status === s).length ?? 0

  return (
    <>
      <PageHeader title="패키지" description="등록된 A/B OTA 패키지. Ready 패키지의 payload 필드는 변경할 수 없습니다."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>패키지 등록</Button>} />
      {list.error && <div className="mb-4"><ErrorBanner error={list.error} onRetry={list.reload} /></div>}
      <Card>
        <DataTable
          rows={rows}
          loading={list.loading}
          rowKey={(p) => p.id}
          onRowClick={setSelected}
          searchText={(p) => `${p.device} ${p.post_build} ${p.pre_builds.join(' ')} ${p.url}`}
          searchPlaceholder="기기, 빌드, URL 검색"
          initialSort={{ key: 'created', dir: 'desc' }}
          toolbar={<Segmented value={status} onChange={setStatus} items={[
            { value: 'all', label: `전체 ${list.data?.length ?? 0}` }, { value: 'ready', label: `Ready ${counts('ready')}` },
            { value: 'rejected', label: `Rejected ${counts('rejected')}` }, { value: 'retired', label: `Retired ${counts('retired')}` },
          ]} />}
          empty={<EmptyState icon={<Boxes className="size-5" />} title="패키지가 없습니다"
            action={<Button variant="primary" onClick={() => setOpen(true)}>패키지 등록</Button>} />}
          columns={[
            { key: 'status', header: '상태', cell: (p) => <PackageBadge status={p.status} /> },
            { key: 'device', header: '기기', sort: (p) => p.device, cell: (p) => <span className="font-medium">{p.device}</span> },
            { key: 'target', header: '대상 빌드', cell: (p) => <Mono>{shortFingerprint(p.post_build).split(' · ').slice(1).join(' · ')}</Mono> },
            { key: 'type', header: '유형', sort: (p) => p.type, cell: (p) => (
              <span className="flex items-center gap-1.5"><Badge tone={p.type === 'incremental' ? 'accent' : 'neutral'}>{p.type}</Badge>
                {p.type === 'incremental' && <span className="text-xs text-muted">source {p.pre_builds.length}</span>}</span>) },
            { key: 'spl', header: '보안 패치', sort: (p) => p.post_spl, cell: (p) => p.post_spl },
            { key: 'size', header: '크기', align: 'right', sort: (p) => p.file_size, cell: (p) => bytes(p.file_size) },
            { key: 'created', header: '등록', align: 'right', sort: (p) => p.created_at,
              cell: (p) => <span className="text-muted">{relativeTime(p.created_at)}</span> },
          ]}
        />
      </Card>

      <Drawer open={!!selected} onClose={() => setSelected(null)} title={selected ? shortFingerprint(selected.post_build) : ''}
        subtitle={selected && <span className="flex items-center gap-2"><PackageBadge status={selected.status} /><Badge>{selected.type}</Badge>#{selected.id}</span>}
        actions={selected?.status === 'ready' && (
          <Button size="sm" variant="ghost" icon={<Archive className="size-3.5" />} onClick={() => setRetire(selected)}>Retire</Button>)}>
        {selected && (
          <div className="space-y-6">
            {selected.reject_reasons.length > 0 && (
              <div className="rounded-md border border-critical/30 bg-critical/5 p-3">
                <p className="mb-1 text-xs font-semibold text-critical">거부 사유</p>
                <ul className="list-disc space-y-1 pl-5 text-xs text-ink">{selected.reject_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              </div>
            )}
            <KeyValue items={[
              ['대상 빌드', <Mono>{selected.post_build}</Mono>],
              ['Source 빌드', selected.pre_builds.length ? selected.pre_builds.map((b) => <Mono key={b} className="block">{b}</Mono>) : '— (full)'],
              ['보안 패치', selected.post_spl],
              ['빌드 시각', dateTime(new Date(selected.post_timestamp * 1000).toISOString())],
              ['플래그', <span className="flex gap-1">{selected.wipe && <Badge tone="serious">wipe</Badge>}
                {selected.spl_downgrade && <Badge tone="serious">spl_downgrade</Badge>}
                {!selected.wipe && !selected.spl_downgrade && '—'}</span>],
              ['크기', `${bytes(selected.file_size)} (payload ${bytes(selected.payload_size)})`],
              ['SHA-256', selected.sha256 ? <Mono className="break-all">{selected.sha256}</Mono> : '미제공'],
              ['등록', `${dateTime(selected.created_at)} · ${selected.created_by}`],
            ]} />
            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-medium text-muted">URL</h3><CopyButton value={selected.url} />
              </div>
              <Mono className="block break-all rounded-md bg-page p-2.5">{selected.url}</Mono>
            </section>
            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-medium text-muted">applyPayload 인자</h3>
                <CopyButton value={Object.entries(selected.payload_properties).map(([k, v]) => `${k}=${v}`).join('\n')} label="헤더 복사" />
              </div>
              <pre className="scrollbar-thin overflow-x-auto rounded-md bg-page p-3 font-mono text-[11.5px] leading-relaxed text-ink">
{`offset = ${selected.payload_offset}
size   = ${selected.payload_size}
${Object.entries(selected.payload_properties).map(([k, v]) => `${k}=${v}`).join('\n')}`}
              </pre>
            </section>
            <section>
              <h3 className="mb-2 text-xs font-medium text-muted">streaming property files</h3>
              <ul className="space-y-1">{selected.streaming_property_files.split(',').map((e) => {
                const [name, offset, size] = e.split(':')
                return (
                  <li key={e} className="flex justify-between gap-3 rounded bg-page px-2.5 py-1.5 text-xs">
                    <Mono>{name}</Mono><span className="tabular text-muted">@{num(Number(offset))} · {bytes(Number(size))}</span>
                  </li>
                )
              })}</ul>
            </section>
          </div>
        )}
      </Drawer>

      <RegisterDialog open={open} onClose={() => setOpen(false)} onDone={() => { setOpen(false); list.reload() }} />
      <ConfirmDialog open={!!retire} onClose={() => setRetire(null)} title="패키지를 Retire 할까요?" confirmLabel="Retire" danger
        description="신규 할당에서 제외됩니다. 이미 설치 중인 기기에는 영향이 없고, 되돌릴 수 없습니다."
        onConfirm={async () => {
          if (!retire) return
          const p = await api.retirePackage(retire.id)
          toast({ kind: 'success', title: '패키지를 Retire 했습니다' })
          setSelected(p)
          list.reload()
        }} />
    </>
  )
}
