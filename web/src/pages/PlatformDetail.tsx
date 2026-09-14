import { ExternalLink, FileUp, Play, ShieldAlert, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { PageHeader } from '../components/layout'
import { Drawer, useToast } from '../components/ui/overlay'
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Input, KeyValue, Mono, Segmented, Select,
  Skeleton, Textarea } from '../components/ui/primitives'
import { Badge, ReadyBadge, SeverityBadge, WORK_STATUS_LABEL } from '../components/ui/status'
import { api, type Finding, type Severity, type WorkStatus } from '../lib/api'
import { dateTime, relativeTime } from '../lib/format'
import { useAsync } from '../lib/hooks'

function FindingDrawer({ finding, onClose, onSaved }: { finding: Finding | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [status, setStatus] = useState<WorkStatus>('todo')
  const [owner, setOwner] = useState('')
  const [reason, setReason] = useState('')
  const [ref, setRef] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!finding) return
    setStatus(finding.status ?? 'todo')
    setOwner(finding.owner ?? '')
    setReason(finding.waive_reason ?? '')
    setRef(finding.external_ref ?? '')
  }, [finding])

  const save = async () => {
    if (!finding?.work_item_id) return
    setBusy(true)
    try {
      await api.patchWorkItem(finding.work_item_id, {
        status, owner: owner || null, waive_reason: status === 'waived' ? reason : null, external_ref: ref || null,
      })
      toast({ kind: 'success', title: '작업 항목을 저장했습니다' })
      onSaved()
      onClose()
    } catch (e) {
      toast({ kind: 'error', title: '저장 실패', description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Drawer open={!!finding} onClose={onClose} title={finding?.title ?? ''}
      subtitle={finding && <span className="flex items-center gap-2"><SeverityBadge severity={finding.severity} /><Mono>{finding.rule_id}</Mono></span>}>
      {finding && (
        <div className="space-y-6">
          <section>
            <h3 className="mb-2 text-xs font-medium text-muted">상세</h3>
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{finding.detail}</p>
          </section>
          {finding.sources.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-medium text-muted">근거</h3>
              <ul className="space-y-1">
                {finding.sources.map((s) => (
                  <li key={s}><a href={s} target="_blank" rel="noreferrer"
                    className="inline-flex items-center gap-1 break-all text-xs text-accent-ink hover:underline">
                    {s}<ExternalLink className="size-3 shrink-0" /></a></li>
                ))}
              </ul>
            </section>
          )}
          {finding.work_item_id ? (
            <section className="space-y-3 rounded-lg border border-line p-4">
              <h3 className="text-xs font-medium text-muted">작업 항목</h3>
              <Segmented value={status} onChange={setStatus}
                items={(Object.keys(WORK_STATUS_LABEL) as WorkStatus[]).map((s) => ({ value: s, label: WORK_STATUS_LABEL[s] }))} />
              <div className="grid grid-cols-2 gap-3">
                <Field label="담당자"><Input value={owner} onChange={(e) => setOwner(e.target.value)} /></Field>
                <Field label="외부 참조" hint="예: Jira 키"><Input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="BSP-1234" /></Field>
              </div>
              {status === 'waived' && (
                <Field label="면제 사유" hint="면제하려면 필수입니다">
                  <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
              )}
              <div className="flex justify-end">
                <Button variant="primary" loading={busy} disabled={status === 'waived' && !reason.trim()} onClick={save}>저장</Button>
              </div>
            </section>
          ) : <p className="text-xs text-muted">Info 항목은 작업 항목을 만들지 않습니다.</p>}
        </div>
      )}
    </Drawer>
  )
}

export default function PlatformDetailPage({ id }: { id: number }) {
  const toast = useToast()
  const platform = useAsync(() => api.platform(id), [id])
  const kb = useAsync(() => api.kb(), [])
  const runs = useAsync(() => api.runs(id), [id])
  const [runId, setRunId] = useState<number>()
  const run = useAsync(() => (runId ? api.run(runId) : Promise.resolve(undefined)), [runId])
  const [target, setTarget] = useState('')
  const [running, setRunning] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [filter, setFilter] = useState<'open' | 'all' | Severity>('open')
  const [selected, setSelected] = useState<Finding | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!runId && runs.data?.length) setRunId(runs.data[0].id)
  }, [runs.data, runId])

  const p = platform.data
  const targets = (kb.data?.releases ?? []).map((r) => r.release)
  useEffect(() => {
    if (!target && targets.length) setTarget(targets.includes('17') ? '17' : targets[targets.length - 1])
  }, [targets, target])

  const evaluate = async () => {
    setRunning(true)
    try {
      const r = await api.createRun(id, target)
      toast({ kind: r.ready ? 'success' : 'warning', title: r.ready ? '업그레이드 가능' : `Blocker ${r.counts.blocker}건`,
        description: r.hal_check })
      runs.reload()
      setRunId(r.id)
    } catch (e) {
      toast({ kind: 'error', title: '판정 실패', description: (e as Error).message })
    } finally {
      setRunning(false)
    }
  }

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setUploading(true)
    try {
      const r = await api.uploadManifest(id, Array.from(files))
      toast({ kind: 'success', title: `HAL 인스턴스 ${r.hals.length}개 반영`,
        description: Object.entries(r.hal_instances_by_format).map(([k, v]) => `${k} ${v}`).join(' · ') })
      platform.reload()
    } catch (e) {
      toast({ kind: 'error', title: 'manifest 업로드 실패', description: (e as Error).message })
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (platform.error) return <ErrorBanner error={platform.error} onRetry={platform.reload} />
  if (!p) return <div className="space-y-4"><Skeleton className="h-12 w-1/3" /><Skeleton className="h-64" /></div>

  const findings = (run.data?.findings ?? []).filter((f) =>
    filter === 'all' ? true : filter === 'open' ? f.severity !== 'info' && !['done', 'waived'].includes(f.status ?? '')
      : f.severity === filter)

  return (
    <>
      <PageHeader
        title={p.name}
        description={`${p.soc} · 현재 Android ${p.android_version}`}
        meta={<><Badge><Mono>{p.kernel_branch}</Mono></Badge>{p.fcm_target_level && <Badge>FCM {p.fcm_target_level}</Badge>}
          {p.uses_ion && <Badge tone="serious">ION</Badge>}{p.uses_vndk && <Badge tone="serious">VNDK</Badge>}</>}
        actions={<>
          <input ref={fileRef} type="file" accept=".xml" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
          <Button icon={<Upload className="size-3.5" />} loading={uploading} onClick={() => fileRef.current?.click()}>Manifest 업로드</Button>
          <Select value={target} onChange={(e) => setTarget(e.target.value)} className="w-32" aria-label="목표 릴리스">
            {targets.map((t) => <option key={t} value={t}>Android {t}</option>)}
          </Select>
          <Button variant="primary" icon={<Play className="size-3.5" />} loading={running} disabled={!target} onClick={evaluate}>판정 실행</Button>
        </>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4">
          <Card>
            <CardHeader title="프로파일" />
            <div className="p-4">
              <KeyValue items={[
                ['VNDK', p.uses_vndk ? '사용' : '미사용'],
                ['ION', p.uses_ion ? '사용' : '미사용'],
                ['16 KB 페이지', p.supports_16kb ? '지원' : '미지원'],
                ['memfd sepolicy', p.sepolicy_memfd_ready ? '대응 완료' : '미대응'],
                ['지원 종료 목표', p.support_until ?? '—'],
                ['Manifest', p.manifest ? `HAL ${p.manifest.hal_count} · ${relativeTime(p.manifest.uploaded_at)}` : '없음'],
              ]} />
            </div>
          </Card>
          <Card>
            <CardHeader title="판정 이력" />
            {runs.data?.length ? (
              <ul className="divide-y divide-line">
                {runs.data.map((r) => (
                  <li key={r.id}>
                    <button onClick={() => setRunId(r.id)}
                      className={`flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-page ${r.id === runId ? 'bg-accent/5' : ''}`}>
                      <span className="text-[13px] text-ink">Android {r.target_release}</span>
                      <span className="text-xs text-muted">{relativeTime(r.created_at)} · {r.created_by}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="px-4 py-6 text-center text-xs text-muted">아직 판정하지 않았습니다</p>}
          </Card>
        </div>

        <Card className="lg:col-span-2">
          {!run.data ? (
            <EmptyState icon={<ShieldAlert className="size-5" />} title="판정 결과가 없습니다"
              description="목표 릴리스를 고르고 판정을 실행하세요. Manifest 와 해당 레벨의 compatibility matrix 가 있으면 HAL 단위 검사도 포함됩니다."
              action={<Button variant="primary" icon={<FileUp className="size-3.5" />} loading={running} disabled={!target} onClick={evaluate}>판정 실행</Button>} />
          ) : (
            <>
              <CardHeader
                title={<span className="flex items-center gap-2">Android {run.data.current_release} → {run.data.target_release} <ReadyBadge ready={run.data.ready} /></span>}
                description={`${dateTime(run.data.created_at)} · KB ${run.data.kb_version} · 기준일 ${run.data.as_of}`}
                actions={<Segmented value={filter} onChange={setFilter} items={[
                  { value: 'open', label: '미해결' }, { value: 'blocker', label: `Blocker ${run.data.counts.blocker}` },
                  { value: 'warning', label: `Warning ${run.data.counts.warning}` }, { value: 'all', label: '전체' },
                ]} />}
              />
              {findings.length === 0 ? (
                <p className="py-12 text-center text-[13px] text-muted">
                  {run.data.findings.length === 0 ? '발견된 문제가 없습니다.' : '이 필터에 해당하는 항목이 없습니다.'}
                </p>
              ) : (
                <ul className="divide-y divide-line">
                  {findings.map((f) => (
                    <li key={f.id}>
                      <button onClick={() => setSelected(f)} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-page">
                        <div className="w-20 shrink-0 pt-0.5"><SeverityBadge severity={f.severity} /></div>
                        <div className="min-w-0 flex-1">
                          <p className="text-[13px] font-medium text-ink">{f.title}</p>
                          <p className="mt-0.5 line-clamp-2 text-xs text-muted">{f.detail}</p>
                        </div>
                        <div className="shrink-0 text-right text-xs">
                          {f.status && <Badge tone={f.status === 'done' ? 'good' : f.status === 'waived' ? 'neutral' : f.status === 'in_progress' ? 'accent' : 'neutral'}>
                            {WORK_STATUS_LABEL[f.status]}</Badge>}
                          {f.owner && <p className="mt-1 text-muted">{f.owner}</p>}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Card>
      </div>
      <FindingDrawer finding={selected} onClose={() => setSelected(null)} onSaved={run.reload} />
    </>
  )
}
