import { Cpu, ExternalLink, FileCog, FileUp, Play, ShieldAlert, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { PageHeader } from '../components/layout'
import { Drawer, useToast } from '../components/ui/overlay'
import { Button, Card, CardHeader, cx, EmptyState, ErrorBanner, Field, Input, KeyValue, Mono, Segmented, Select,
  Skeleton, Textarea } from '../components/ui/primitives'
import { Badge, ReadyBadge, SeverityBadge, WORK_STATUS_LABEL } from '../components/ui/status'
import { api, ApiError, type Finding, type KernelConfigHints, type Platform, type Severity, type UprevReport, type WorkStatus } from '../lib/api'
import { dateTime, relativeTime } from '../lib/format'
import { useAsync } from '../lib/hooks'
import PlatformDrivers from './PlatformDrivers'
import { localized, useLang, useT } from '../lib/i18n'
import { HUE, hueOf } from '../lib/palette'

function FindingDrawer({ finding, onClose, onSaved }: { finding: Finding | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const t = useT()
  const [lang] = useLang()
  const text = finding ? localized(finding, lang) : null
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
      toast({ kind: 'success', title: t('작업 항목을 저장했습니다', 'Work item saved') })
      onSaved()
      onClose()
    } catch (e) {
      toast({ kind: 'error', title: t('저장 실패', 'Save failed'), description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Drawer open={!!finding} onClose={onClose} title={text?.title ?? ''}
      subtitle={finding && <span className="flex items-center gap-2"><SeverityBadge severity={finding.severity} /><Mono>{finding.rule_id}</Mono></span>}>
      {finding && (
        <div className="space-y-6">
          <section>
            <h3 className="mb-2 text-xs font-medium text-muted">{t('상세', 'Details')}</h3>
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{text?.detail}</p>
          </section>
          {finding.sources.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-medium text-muted">{t('근거', 'Sources')}</h3>
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
            <section className={cx('space-y-3 rounded-lg border-l-4 p-4 ring-1 ring-inset', HUE.violet.border, HUE.violet.ring)}>
              <h3 className={cx('text-xs font-medium', HUE.violet.text)}>{t('작업 항목', 'Work item')}</h3>
              <Segmented value={status} onChange={setStatus}
                items={(Object.keys(WORK_STATUS_LABEL) as WorkStatus[]).map((s) => ({ value: s, label: WORK_STATUS_LABEL[s] }))} />
              <div className="grid grid-cols-2 gap-3">
                <Field label={t('담당자', 'Owner')}><Input value={owner} onChange={(e) => setOwner(e.target.value)} /></Field>
                <Field label={t('외부 참조', 'External ref')} hint={t('예: Jira 키', 'e.g. Jira key')}><Input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="BSP-1234" /></Field>
              </div>
              {status === 'waived' && (
                <Field label={t('면제 사유', 'Waiver reason')} hint={t('면제하려면 필수입니다', 'Required to waive')}>
                  <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
              )}
              <div className="flex justify-end">
                <Button variant="primary" loading={busy} disabled={status === 'waived' && !reason.trim()} onClick={save}>{t('저장', 'Save')}</Button>
              </div>
            </section>
          ) : <p className="text-xs text-muted">{t('Info 항목은 작업 항목을 만들지 않습니다.', 'Info findings do not create work items.')}</p>}
        </div>
      )}
    </Drawer>
  )
}

function configSummary(h: KernelConfigHints, t: (ko: string, en: string) => string) {
  return t(`${h.page_size_kb ?? '?'} KB 페이지 · ION ${h.uses_ion ? '사용' : '미사용'} · DMA-BUF heaps ${h.dmabuf_heaps ? '있음' : '없음'}`,
    `${h.page_size_kb ?? '?'} KB pages · ION ${h.uses_ion ? 'used' : 'not used'} · DMA-BUF heaps ${h.dmabuf_heaps ? 'present' : 'absent'}`)
}

const KERNEL_RELEASE_RE = /^\d+\.\d+\.\d+-android\d+-\d+(-.+)?$/

function KernelCard({ platform, uprev, kernelBranch, onKernelBranch, onChanged }: {
  platform: Platform; uprev: UprevReport | undefined; kernelBranch: string; onKernelBranch: (b: string) => void
  onChanged: () => void
}) {
  const toast = useToast()
  const t = useT()
  const kernel = useAsync(() => api.kernel(platform.id).catch((e) => {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }), [platform.id, platform.kernel?.uploaded_at])
  const [release, setRelease] = useState('')
  const [busy, setBusy] = useState<'release' | 'config' | 'modules'>()
  const configRef = useRef<HTMLInputElement>(null)
  const modulesRef = useRef<HTMLInputElement>(null)

  const send = async (kind: 'release' | 'config' | 'modules', parts: Parameters<typeof api.uploadKernel>[1]) => {
    setBusy(kind)
    try {
      const r = await api.uploadKernel(platform.id, parts)
      const h = r.config_hints
      toast({ kind: 'success',
        title: kind === 'modules' ? t(`모듈 ${r.modules.length}개 분석`, `Analyzed ${r.modules.length} modules`)
          : t('커널 정보를 반영했습니다', 'Kernel info updated'),
        description: h ? configSummary(h, t) : undefined })
      setRelease('')
      onChanged()
    } catch (e) {
      toast({ kind: 'error', title: t('커널 산출물 업로드 실패', 'Kernel artifact upload failed'), description: (e as Error).message })
    } finally {
      setBusy(undefined)
      if (configRef.current) configRef.current.value = ''
      if (modulesRef.current) modulesRef.current.value = ''
    }
  }

  const k = kernel.data
  const hints = k?.config?.hints
  const importCount = k?.modules.reduce((n, m) => n + m.undefined_count, 0) ?? 0
  return (
    <Card>
      <CardHeader hue="indigo" title={t('커널', 'Kernel')} description={t('uname -r · /proc/config.gz · vendor_dlkm 모듈(.ko)', 'uname -r · /proc/config.gz · vendor_dlkm modules (.ko)')} />
      <div className="space-y-4 p-4">
        {kernel.error ? <ErrorBanner error={kernel.error} onRetry={kernel.reload} /> : (
          <KeyValue items={[
            [t('브랜치', 'Branch'), <Badge hue={hueOf(platform.kernel_branch)}><Mono className="text-[11px]">{platform.kernel_branch}</Mono></Badge>],
            [t('릴리스', 'Release'), k?.kernel_release ? <Mono className="break-all">{k.kernel_release}</Mono> : '—'],
            ['KMI generation', k?.kmi_generation != null ? <Badge hue="purple">KMI {k.kmi_generation}</Badge> : '—'],
            ['config', hints ? configSummary(hints, t) : t('없음', 'None')],
            [t('vendor 모듈', 'vendor modules'), k?.modules.length
              ? t(`${k.modules.length}개 · import 심볼 ${importCount}`, `${k.modules.length} · ${importCount} imported symbols`)
              : t('없음', 'None')],
          ]} />
        )}
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); send('release', { kernel_release: release.trim() }) }}>
          <Input value={release} onChange={(e) => setRelease(e.target.value)} placeholder="6.1.75-android14-11-g…" aria-label="uname -r" className="font-mono" />
          <Button type="submit" loading={busy === 'release'} disabled={!KERNEL_RELEASE_RE.test(release.trim())}>{t('저장', 'Save')}</Button>
        </form>
        <div className="flex flex-wrap gap-2">
          <input ref={configRef} type="file" className="hidden" onChange={(e) => e.target.files?.[0] && send('config', { config: e.target.files[0] })} />
          <input ref={modulesRef} type="file" accept=".ko" multiple className="hidden"
            onChange={(e) => e.target.files?.length && send('modules', { modules: Array.from(e.target.files) })} />
          <Button icon={<FileCog className="size-3.5" />} loading={busy === 'config'} onClick={() => configRef.current?.click()}>{t('config 업로드', 'Upload config')}</Button>
          <Button icon={<Cpu className="size-3.5" />} loading={busy === 'modules'} onClick={() => modulesRef.current?.click()}>{t('모듈(.ko) 업로드', 'Upload modules (.ko)')}</Button>
        </div>
        {uprev && (
          <section>
            <h3 className="mb-2 text-xs font-medium text-muted">{t(`Android ${uprev.target_release} 판정 기준 커널`, `Kernel for Android ${uprev.target_release} check`)}</h3>
            <ul className="space-y-1">
              {uprev.candidates.map((c) => (
                <li key={c.branch}>
                  <button type="button" onClick={() => onKernelBranch(c.branch)}
                    className={`flex w-full flex-wrap items-center gap-1.5 rounded-md px-2 py-1.5 text-left hover:bg-page ${c.branch === kernelBranch ? 'bg-accent/5 ring-1 ring-inset ring-accent/30' : ''}`}>
                    <span className="mr-auto inline-flex items-center gap-1.5">
                      <span aria-hidden className={cx('size-2 shrink-0 rounded-full', HUE[hueOf(c.branch)].dot)} />
                      <Mono className="text-ink">{c.branch}</Mono>
                    </span>
                    {c.is_current && <Badge>{t('현재', 'Current')}</Badge>}
                    {c.branch === uprev.recommended && <Badge tone="accent">{t('권장', 'Recommended')}</Badge>}
                    {c.eol_passed && <Badge tone="critical">{t('EOL 경과', 'Past EOL')}</Badge>}
                    {c.unsupported_from && <Badge tone="warning">{t(`${c.unsupported_from} 미지원`, `Unsupported from ${c.unsupported_from}`)}</Badge>}
                    {c.covers_support_until === false && <Badge tone="serious">{t('지원 기간 미충족', 'Support period too short')}</Badge>}
                    {!c.symbol_list_uploaded && <Badge>{t('symbol list 없음', 'No symbol list')}</Badge>}
                    <span className="w-full text-[11px] text-muted">EOL {c.eol}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Card>
  )
}

export default function PlatformDetailPage({ id }: { id: number }) {
  const toast = useToast()
  const t = useT()
  const [lang] = useLang()
  const platform = useAsync(() => api.platform(id), [id])
  const kb = useAsync(() => api.kb(), [])
  const runs = useAsync(() => api.runs(id), [id])
  const [runId, setRunId] = useState<number>()
  const run = useAsync(() => (runId ? api.run(runId) : Promise.resolve(undefined)), [runId])
  const [target, setTarget] = useState('')
  const [kernelBranch, setKernelBranch] = useState('')
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

  const uprev = useAsync(() => (target ? api.kernelUprev(id, target) : Promise.resolve(undefined)), [id, target])
  useEffect(() => {
    // 목표 릴리스가 바뀌면 판정 기준 커널을 현재 커널로 되돌린다
    if (p) setKernelBranch(p.kernel_branch)
  }, [target, p?.kernel_branch])

  const evaluate = async () => {
    setRunning(true)
    try {
      const planned = kernelBranch && kernelBranch !== p?.kernel_branch ? kernelBranch : undefined
      const r = await api.createRun(id, target, planned)
      toast({ kind: r.ready ? 'success' : 'warning', title: r.ready ? t('업그레이드 가능', 'Ready to upgrade') : t(`Blocker ${r.counts.blocker}건`, `${r.counts.blocker} blockers`),
        description: [r.hal_check, r.kmi_check].filter(Boolean).join(' · ') })
      runs.reload()
      setRunId(r.id)
    } catch (e) {
      toast({ kind: 'error', title: t('판정 실패', 'Check failed'), description: (e as Error).message })
    } finally {
      setRunning(false)
    }
  }

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setUploading(true)
    try {
      const r = await api.uploadManifest(id, Array.from(files))
      toast({ kind: 'success', title: t(`HAL 인스턴스 ${r.hals.length}개 반영`, `Loaded ${r.hals.length} HAL instances`),
        description: Object.entries(r.hal_instances_by_format).map(([k, v]) => `${k} ${v}`).join(' · ') })
      platform.reload()
    } catch (e) {
      toast({ kind: 'error', title: t('manifest 업로드 실패', 'Manifest upload failed'), description: (e as Error).message })
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
        description={t(`${p.soc} · 현재 Android ${p.android_version}`, `${p.soc} · currently Android ${p.android_version}`)}
        meta={<><Badge hue={hueOf(p.android_version)}>Android {p.android_version}</Badge>
          <Badge hue={hueOf(p.kernel_branch)}><Mono className="text-[11px]">{p.kernel_branch}</Mono></Badge>{p.fcm_target_level && <Badge hue="cyan">FCM {p.fcm_target_level}</Badge>}
          {p.uses_ion && <Badge tone="serious">ION</Badge>}{p.uses_vndk && <Badge tone="serious">VNDK</Badge>}</>}
        actions={<>
          <input ref={fileRef} type="file" accept=".xml" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
          <Button icon={<Upload className="size-3.5" />} loading={uploading} onClick={() => fileRef.current?.click()}>{t('Manifest 업로드', 'Upload manifest')}</Button>
          <Select value={target} onChange={(e) => setTarget(e.target.value)} className="w-32" aria-label={t('목표 릴리스', 'Target release')}>
            {targets.map((r) => <option key={r} value={r}>Android {r}</option>)}
          </Select>
          <Select value={kernelBranch} onChange={(e) => setKernelBranch(e.target.value)} className="w-52" aria-label={t('판정 기준 커널', 'Kernel for check')}>
            {(uprev.data?.candidates ?? [{ branch: p.kernel_branch }]).map((c) => (
              <option key={c.branch} value={c.branch}>{c.branch === p.kernel_branch ? t(`${c.branch} (현재)`, `${c.branch} (current)`) : c.branch}</option>))}
          </Select>
          <Button variant="primary" icon={<Play className="size-3.5" />} loading={running} disabled={!target} onClick={evaluate}>{t('판정 실행', 'Run check')}</Button>
        </>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4">
          <Card>
            <CardHeader hue="sky" title={t('프로파일', 'Profile')} />
            <div className="p-4">
              <KeyValue items={[
                ['VNDK', p.uses_vndk ? t('사용', 'Used') : t('미사용', 'Not used')],
                ['ION', p.uses_ion ? t('사용', 'Used') : t('미사용', 'Not used')],
                [t('16 KB 페이지', '16 KB pages'), p.supports_16kb ? t('지원', 'Supported') : t('미지원', 'Not supported')],
                ['memfd sepolicy', p.sepolicy_memfd_ready ? t('대응 완료', 'Done') : t('미대응', 'Pending')],
                [t('지원 종료 목표', 'Support until'), p.support_until ?? '—'],
                ['Manifest', p.manifest
                  ? <span className="inline-flex items-center gap-1.5"><Badge hue="sky">HAL {p.manifest.hal_count}</Badge><span className="text-muted">{relativeTime(p.manifest.uploaded_at)}</span></span>
                  : t('없음', 'None')],
              ]} />
            </div>
          </Card>
          <KernelCard platform={p} uprev={uprev.data} kernelBranch={kernelBranch} onKernelBranch={setKernelBranch}
            onChanged={() => { platform.reload(); uprev.reload() }} />
          <Card>
            <CardHeader hue="teal" title={t('판정 이력', 'Check history')} />
            {runs.data?.length ? (
              <ul className="divide-y divide-line">
                {runs.data.map((r) => (
                  <li key={r.id}>
                    <button onClick={() => setRunId(r.id)}
                      className={`flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-page ${r.id === runId ? 'bg-accent/5' : ''}`}>
                      <span className="flex items-center gap-2 text-[13px] text-ink">
                        <span aria-hidden className={cx('grid size-6 shrink-0 place-items-center rounded-md text-[10px] font-semibold ring-1 ring-inset', HUE[hueOf(r.target_release)].soft, HUE[hueOf(r.target_release)].text, HUE[hueOf(r.target_release)].ring)}>
                          {r.target_release.slice(0, 2)}
                        </span>
                        Android {r.target_release}
                      </span>
                      <span className="text-xs text-muted">{relativeTime(r.created_at)} · {r.created_by}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="px-4 py-6 text-center text-xs text-muted">{t('아직 판정하지 않았습니다', 'No checks yet')}</p>}
          </Card>
        </div>

        <Card className="lg:col-span-2">
          {!run.data ? (
            <EmptyState icon={<ShieldAlert className="size-5" />} title={t('판정 결과가 없습니다', 'No check results')}
              description={t('목표 릴리스를 고르고 판정을 실행하세요. Manifest 와 해당 레벨의 compatibility matrix 가 있으면 HAL 단위 검사도 포함됩니다.',
                'Pick a target release and run a check. If a manifest and the compatibility matrix for that level exist, per-HAL checks are included.')}
              action={<Button variant="primary" icon={<FileUp className="size-3.5" />} loading={running} disabled={!target} onClick={evaluate}>{t('판정 실행', 'Run check')}</Button>} />
          ) : (
            <>
              <CardHeader
                hue={hueOf(run.data.target_release)}
                title={<span className="flex flex-wrap items-center gap-2">
                  <Badge hue={hueOf(run.data.current_release)}>Android {run.data.current_release}</Badge>
                  <span className="text-muted">→</span>
                  <Badge hue={hueOf(run.data.target_release)}>Android {run.data.target_release}</Badge>
                  <ReadyBadge ready={run.data.ready} /></span>}
                description={`${dateTime(run.data.created_at)} · KB ${run.data.kb_version} · ${t('기준일', 'as of')} ${run.data.as_of}`
                  + (run.data.kernel_branch ? ` · ${t('커널', 'kernel')} ${run.data.kernel_branch}` : '')}
                actions={<Segmented value={filter} onChange={setFilter} items={[
                  { value: 'open', label: t('미해결', 'Open') }, { value: 'blocker', label: `Blocker ${run.data.counts.blocker}` },
                  { value: 'warning', label: `Warning ${run.data.counts.warning}` }, { value: 'all', label: t('전체', 'All') },
                ]} />}
              />
              {findings.length === 0 ? (
                <p className="py-12 text-center text-[13px] text-muted">
                  {run.data.findings.length === 0 ? t('발견된 문제가 없습니다.', 'No issues found.') : t('이 필터에 해당하는 항목이 없습니다.', 'No items match this filter.')}
                </p>
              ) : (
                <ul className="divide-y divide-line">
                  {findings.map((f) => { const ft = localized(f, lang); return (
                    <li key={f.id}>
                      <button onClick={() => setSelected(f)} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-page">
                        <div className="w-20 shrink-0 pt-0.5"><SeverityBadge severity={f.severity} /></div>
                        <div className="min-w-0 flex-1">
                          <p className="text-[13px] font-medium text-ink">{ft.title}</p>
                          <p className="mt-0.5"><Badge hue={hueOf(f.rule_id.split(/[._-]/)[0])} className="font-mono">{f.rule_id}</Badge></p>
                          <p className="mt-0.5 line-clamp-2 text-xs text-muted">{ft.detail}</p>
                        </div>
                        <div className="shrink-0 text-right text-xs">
                          {f.status && <Badge tone={f.status === 'done' ? 'good' : f.status === 'waived' ? 'neutral' : f.status === 'in_progress' ? 'accent' : 'neutral'}>
                            {WORK_STATUS_LABEL[f.status]}</Badge>}
                          {f.owner && <p className="mt-1 text-muted">{f.owner}</p>}
                        </div>
                      </button>
                    </li>
                  ) })}
                </ul>
              )}
            </>
          )}
        </Card>
      </div>
      <PlatformDrivers platformId={id} kernelBranch={kernelBranch}
        reloadKey={`${p.kernel?.uploaded_at ?? ''}|${p.manifest?.uploaded_at ?? ''}`} />
      <FindingDrawer finding={selected} onClose={() => setSelected(null)} onSaved={run.reload} />
    </>
  )
}
