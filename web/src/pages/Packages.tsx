import { Archive, Boxes, Layers, Plus, ScanSearch, Smartphone, SquareStack } from 'lucide-react'
import { useEffect, useState } from 'react'
import { PageHeader } from '../components/layout'
import { ConfirmDialog, Dialog, Drawer, useToast } from '../components/ui/overlay'
import { Button, Card, CopyButton, cx, EmptyState, ErrorBanner, Field, Input, KeyValue, Mono, Segmented } from '../components/ui/primitives'
import { Badge, PackageBadge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api, type InspectResult, type OtaPackage } from '../lib/api'
import { bytes, dateTime, num, parseFingerprint, relativeTime, shortFingerprint } from '../lib/format'
import { useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'
import { HUE, hueOf, type Hue } from '../lib/palette'

// 패키지 유형(장식용 구분) — 상태는 PackageBadge 가 따로 전한다
const TYPE_HUE: Record<string, Hue> = { full: 'indigo', incremental: 'teal' }

function TypeBadge({ type }: { type: string }) {
  return <Badge hue={TYPE_HUE[type] ?? hueOf(type)} icon={type === 'incremental' ? <Layers className="size-3" /> : <SquareStack className="size-3" />}>{type}</Badge>
}

function DeviceBadge({ device }: { device: string }) {
  return <Badge hue={hueOf(device)} icon={<Smartphone className="size-3" />}>{device}</Badge>
}

/** 대상 빌드: 릴리스는 색 배지, 빌드 ID 는 고정폭 글자 */
function BuildCell({ fingerprint }: { fingerprint: string }) {
  const f = parseFingerprint(fingerprint)
  if (!f.release) return <Mono>{shortFingerprint(fingerprint)}</Mono>
  return (
    <span className="flex items-center gap-1.5">
      <Badge hue={hueOf(`Android ${f.release}`)}>Android {f.release}</Badge>
      <Mono>{f.buildId}</Mono>
    </span>
  )
}

function RegisterDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const t = useT()
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
        toast({ kind: p.status === 'ready' ? 'success' : 'warning', title: p.status === 'ready' ? t('패키지 등록됨', 'Package registered') : t('패키지 거부됨', 'Package rejected'),
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
    <Dialog open={open} onClose={onClose} title={t('OTA 패키지 등록', 'Register OTA package')} width="max-w-2xl"
      description={t('서명된 A/B OTA zip 의 https URL. 서버가 HTTP Range 로 메타데이터만 읽어 검증합니다 (전체 다운로드 없음).', 'https URL of a signed A/B OTA zip. The server verifies it by reading only the metadata via HTTP Range (no full download).')}
      footer={<>
        <Button onClick={onClose}>{t('취소', 'Cancel')}</Button>
        <Button icon={<ScanSearch className="size-3.5" />} loading={busy === 'inspect'} disabled={!url.trim()} onClick={() => run('inspect')}>{t('검사만', 'Inspect only')}</Button>
        <Button variant="primary" loading={busy === 'register'} disabled={!url.trim()} onClick={() => run('register')}>{t('등록', 'Register')}</Button>
      </>}>
      <div className="space-y-3">
        <Field label={t('패키지 URL', 'Package URL')} hint={t('오리진은 ANDROID_OS_PACKAGE_HOSTS 에 있어야 하며 Range 요청과 리다이렉트 없는 응답이 필요합니다', 'The origin must be in ANDROID_OS_PACKAGE_HOSTS and must support Range requests without redirects')}>
          <Input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} className="font-mono text-xs"
            placeholder="https://dl.google.com/dl/android/aosp/lynx-ota-cp2a.260705.006-f4d6d546.zip" />
        </Field>
        <Field label={t('SHA-256 (선택)', 'SHA-256 (optional)')} hint={t('빌드 파이프라인이 계산한 값. 서버는 전체 해시를 계산하지 않습니다', 'Value computed by the build pipeline. The server does not hash the full file')}>
          <Input value={sha} onChange={(e) => setSha(e.target.value.toLowerCase())} className="font-mono text-xs" />
        </Field>
        {error && <ErrorBanner error={error} />}
        {inspect && (
          <div className="rounded-lg border border-line bg-page p-4">
            <div className="mb-3 flex items-center gap-2">
              <PackageBadge status={inspect.ready ? 'ready' : 'rejected'} />
              <TypeBadge type={inspect.package_type} />
              {inspect.range_requests != null && (
                <span className="text-xs text-muted">{t(`Range 요청 ${inspect.range_requests}회 · ${bytes(inspect.bytes_fetched)} 읽음 / ${bytes(inspect.file_size)}`, `${inspect.range_requests} Range requests · read ${bytes(inspect.bytes_fetched)} / ${bytes(inspect.file_size)}`)}</span>
              )}
            </div>
            <KeyValue items={[
              [t('대상 빌드', 'Target build'), <Mono>{inspect.post_build}</Mono>],
              [t('기기', 'Device'), <span className="flex flex-wrap gap-1">{inspect.pre_device.map((d) => <DeviceBadge key={d} device={d} />)}</span>],
              [t('보안 패치', 'Security patch'), inspect.post_spl],
              ['SDK', inspect.post_sdk_level ?? '—'],
              [t('Source 빌드', 'Source builds'), inspect.pre_builds.length ? inspect.pre_builds.map((b) => <Mono key={b} className="block">{b}</Mono>) : '— (full)'],
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
  const t = useT()
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
      <PageHeader title={t('패키지', 'Packages')} description={t('등록된 A/B OTA 패키지. Ready 패키지의 payload 필드는 변경할 수 없습니다.', 'Registered A/B OTA packages. Payload fields of Ready packages are immutable.')}
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>{t('패키지 등록', 'Register package')}</Button>} />
      {list.error && <div className="mb-4"><ErrorBanner error={list.error} onRetry={list.reload} /></div>}
      <Card>
        <DataTable
          rows={rows}
          loading={list.loading}
          rowKey={(p) => p.id}
          onRowClick={setSelected}
          searchText={(p) => `${p.device} ${p.post_build} ${p.pre_builds.join(' ')} ${p.url}`}
          searchPlaceholder={t('기기, 빌드, URL 검색', 'Search device, build, URL')}
          initialSort={{ key: 'created', dir: 'desc' }}
          toolbar={<Segmented value={status} onChange={setStatus} items={[
            { value: 'all', label: t(`전체 ${list.data?.length ?? 0}`, `All ${list.data?.length ?? 0}`) }, { value: 'ready', label: `Ready ${counts('ready')}` },
            { value: 'rejected', label: `Rejected ${counts('rejected')}` }, { value: 'retired', label: `Retired ${counts('retired')}` },
          ]} />}
          empty={<EmptyState icon={<Boxes className="size-5" />} title={t('패키지가 없습니다', 'No packages')}
            action={<Button variant="primary" onClick={() => setOpen(true)}>{t('패키지 등록', 'Register package')}</Button>} />}
          columns={[
            { key: 'status', header: t('상태', 'Status'), cell: (p) => <PackageBadge status={p.status} /> },
            { key: 'device', header: t('기기', 'Device'), sort: (p) => p.device, cell: (p) => <DeviceBadge device={p.device} /> },
            { key: 'target', header: t('대상 빌드', 'Target build'), cell: (p) => <BuildCell fingerprint={p.post_build} /> },
            { key: 'type', header: t('유형', 'Type'), sort: (p) => p.type, cell: (p) => (
              <span className="flex items-center gap-1.5"><TypeBadge type={p.type} />
                {p.type === 'incremental' && <span className="text-xs text-muted">source {p.pre_builds.length}</span>}</span>) },
            { key: 'spl', header: t('보안 패치', 'Security patch'), sort: (p) => p.post_spl, cell: (p) => p.post_spl },
            { key: 'size', header: t('크기', 'Size'), align: 'right', sort: (p) => p.file_size, cell: (p) => bytes(p.file_size) },
            { key: 'created', header: t('등록', 'Registered'), align: 'right', sort: (p) => p.created_at,
              cell: (p) => <span className="text-muted">{relativeTime(p.created_at)}</span> },
          ]}
        />
      </Card>

      <Drawer open={!!selected} onClose={() => setSelected(null)} title={selected ? shortFingerprint(selected.post_build) : ''}
        subtitle={selected && <span className="flex items-center gap-2"><PackageBadge status={selected.status} /><TypeBadge type={selected.type} /><DeviceBadge device={selected.device} />#{selected.id}</span>}
        actions={selected?.status === 'ready' && (
          <Button size="sm" variant="ghost" icon={<Archive className="size-3.5" />} onClick={() => setRetire(selected)}>Retire</Button>)}>
        {selected && (
          <div className="space-y-6">
            {selected.reject_reasons.length > 0 && (
              <div className="rounded-md border border-critical/30 bg-critical/5 p-3">
                <p className="mb-1 text-xs font-semibold text-critical">{t('거부 사유', 'Rejection reasons')}</p>
                <ul className="list-disc space-y-1 pl-5 text-xs text-ink">{selected.reject_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              </div>
            )}
            <KeyValue items={[
              [t('대상 빌드', 'Target build'), <Mono>{selected.post_build}</Mono>],
              [t('Source 빌드', 'Source builds'), selected.pre_builds.length ? selected.pre_builds.map((b) => <Mono key={b} className="block">{b}</Mono>) : '— (full)'],
              [t('보안 패치', 'Security patch'), selected.post_spl],
              [t('빌드 시각', 'Build time'), dateTime(new Date(selected.post_timestamp * 1000).toISOString())],
              [t('플래그', 'Flags'), <span className="flex gap-1">{selected.wipe && <Badge tone="serious">wipe</Badge>}
                {selected.spl_downgrade && <Badge tone="serious">spl_downgrade</Badge>}
                {!selected.wipe && !selected.spl_downgrade && '—'}</span>],
              [t('크기', 'Size'), `${bytes(selected.file_size)} (payload ${bytes(selected.payload_size)})`],
              ['SHA-256', selected.sha256 ? <Mono className="break-all">{selected.sha256}</Mono> : t('미제공', 'Not provided')],
              [t('등록', 'Registered'), `${dateTime(selected.created_at)} · ${selected.created_by}`],
            ]} />
            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-medium text-muted">URL</h3><CopyButton value={selected.url} />
              </div>
              <Mono className="block break-all rounded-md bg-page p-2.5">{selected.url}</Mono>
            </section>
            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-medium text-muted">{t('applyPayload 인자', 'applyPayload arguments')}</h3>
                <CopyButton value={Object.entries(selected.payload_properties).map(([k, v]) => `${k}=${v}`).join('\n')} label={t('헤더 복사', 'Copy headers')} />
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
                  <li key={e} className={cx('flex justify-between gap-3 rounded border-l-4 bg-page px-2.5 py-1.5 text-xs', HUE[hueOf(name)].border)}>
                    <Mono className={HUE[hueOf(name)].text}>{name}</Mono><span className="tabular text-muted">@{num(Number(offset))} · {bytes(Number(size))}</span>
                  </li>
                )
              })}</ul>
            </section>
          </div>
        )}
      </Drawer>

      <RegisterDialog open={open} onClose={() => setOpen(false)} onDone={() => { setOpen(false); list.reload() }} />
      <ConfirmDialog open={!!retire} onClose={() => setRetire(null)} title={t('패키지를 Retire 할까요?', 'Retire this package?')} confirmLabel="Retire" danger
        description={t('신규 할당에서 제외됩니다. 이미 설치 중인 기기에는 영향이 없고, 되돌릴 수 없습니다.', 'It will be excluded from new assignments. Devices already installing are unaffected. This cannot be undone.')}
        onConfirm={async () => {
          if (!retire) return
          const p = await api.retirePackage(retire.id)
          toast({ kind: 'success', title: t('패키지를 Retire 했습니다', 'Package retired') })
          setSelected(p)
          list.reload()
        }} />
    </>
  )
}
