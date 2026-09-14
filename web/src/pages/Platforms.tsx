import { Cpu, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { PageHeader } from '../components/layout'
import { Dialog, useToast } from '../components/ui/overlay'
import { Button, Card, EmptyState, ErrorBanner, Field, Input, Mono, Switch } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api, type Platform } from '../lib/api'
import { relativeTime } from '../lib/format'
import { navigate, useAsync, useRoute } from '../lib/hooks'

const EMPTY = {
  name: '', soc: '', android_version: '16', kernel_branch: 'android16-6.12', fcm_target_level: '',
  uses_vndk: false, uses_ion: false, supports_16kb: false, sepolicy_memfd_ready: false, support_until: '',
}

export function NewPlatformDialog({ open, onClose, onCreated }: {
  open: boolean; onClose: () => void; onCreated: (p: Platform) => void
}) {
  const kb = useAsync(() => api.kb(), [])
  const toast = useToast()
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error>()
  useEffect(() => { if (open) { setForm(EMPTY); setError(undefined) } }, [open])
  const set = <K extends keyof typeof EMPTY>(k: K, v: (typeof EMPTY)[K]) => setForm((f) => ({ ...f, [k]: v }))

  const submit = async () => {
    setBusy(true)
    try {
      const p = await api.createPlatform({
        ...form,
        fcm_target_level: form.fcm_target_level || null,
        support_until: form.support_until || null,
      })
      toast({ kind: 'success', title: `플랫폼 ${p.name} 등록됨` })
      onCreated(p)
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="플랫폼 등록" width="max-w-xl"
      description="SoC/BSP 기준선의 현재 상태를 입력합니다. 이후 VINTF manifest 를 올리면 HAL 단위로도 판정합니다."
      footer={<><Button onClick={onClose}>취소</Button>
        <Button variant="primary" loading={busy} disabled={!form.name || !form.soc} onClick={submit}>등록</Button></>}>
      <div className="space-y-4">
        {error && <ErrorBanner error={error} />}
        <div className="grid grid-cols-2 gap-3">
          <Field label="이름"><Input autoFocus value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="pony-bsp" /></Field>
          <Field label="SoC"><Input value={form.soc} onChange={(e) => set('soc', e.target.value)} placeholder="exynos-2600" /></Field>
          <Field label="현재 Android 버전" hint="예: 15, 16, 16-QPR2">
            <Input value={form.android_version} onChange={(e) => set('android_version', e.target.value)} />
          </Field>
          <Field label="커널 브랜치 (ACK)">
            <Input list="kernel-branches" value={form.kernel_branch} onChange={(e) => set('kernel_branch', e.target.value)} className="font-mono" />
            <datalist id="kernel-branches">{kb.data?.kernel_branches.map((k) => <option key={k.branch} value={k.branch} />)}</datalist>
          </Field>
          <Field label="Target FCM level" hint="manifest 업로드 시 자동 설정">
            <Input value={form.fcm_target_level} onChange={(e) => set('fcm_target_level', e.target.value.replace(/\D/g, ''))} placeholder="202504" />
          </Field>
          <Field label="제품 지원 종료 목표일" hint="커널 EOL 과 비교">
            <Input type="date" value={form.support_until} onChange={(e) => set('support_until', e.target.value)} />
          </Field>
        </div>
        <div className="rounded-md border border-line px-3 py-1.5">
          <Switch label="VNDK 사용" checked={form.uses_vndk} onChange={(v) => set('uses_vndk', v)} />
          <Switch label="ION 메모리 할당자 사용" checked={form.uses_ion} onChange={(v) => set('uses_ion', v)} />
          <Switch label="16 KB 페이지 지원" checked={form.supports_16kb} onChange={(v) => set('supports_16kb', v)} />
          <Switch label="sepolicy memfd_class 대응 완료" checked={form.sepolicy_memfd_ready} onChange={(v) => set('sepolicy_memfd_ready', v)} />
        </div>
      </div>
    </Dialog>
  )
}

export default function PlatformsPage() {
  const { query } = useRoute()
  const list = useAsync(() => api.platforms(), [])
  const [open, setOpen] = useState(query.get('new') === '1')

  return (
    <>
      <PageHeader title="플랫폼" description="업그레이드 대상 SoC/BSP 기준선. 목표 릴리스를 골라 준비도를 판정합니다."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>플랫폼 등록</Button>} />
      {list.error && <div className="mb-4"><ErrorBanner error={list.error} onRetry={list.reload} /></div>}
      <Card>
        <DataTable
          rows={list.data}
          loading={list.loading}
          rowKey={(p) => p.id}
          onRowClick={(p) => navigate(`/platforms/${p.id}`)}
          searchText={(p) => `${p.name} ${p.soc} ${p.kernel_branch}`}
          searchPlaceholder="이름, SoC, 커널 검색"
          initialSort={{ key: 'name', dir: 'asc' }}
          empty={<EmptyState icon={<Cpu className="size-5" />} title="등록된 플랫폼이 없습니다"
            action={<Button variant="primary" onClick={() => setOpen(true)}>플랫폼 등록</Button>} />}
          columns={[
            { key: 'name', header: '이름', sort: (p) => p.name, cell: (p) => <span className="font-medium">{p.name}</span> },
            { key: 'soc', header: 'SoC', sort: (p) => p.soc, cell: (p) => p.soc },
            { key: 'android', header: 'Android', sort: (p) => p.android_version, cell: (p) => p.android_version },
            { key: 'kernel', header: '커널', sort: (p) => p.kernel_branch, cell: (p) => <Mono>{p.kernel_branch}</Mono> },
            { key: 'fcm', header: 'FCM', cell: (p) => p.fcm_target_level ?? <span className="text-muted">—</span> },
            { key: 'manifest', header: 'Manifest', cell: (p) => p.manifest
              ? <Badge tone="accent">HAL {p.manifest.hal_count}</Badge> : <span className="text-muted">없음</span> },
            { key: 'flags', header: '레거시 의존', cell: (p) => (
              <div className="flex gap-1">
                {p.uses_ion && <Badge tone="serious">ION</Badge>}
                {p.uses_vndk && <Badge tone="serious">VNDK</Badge>}
                {!p.uses_ion && !p.uses_vndk && <span className="text-muted">—</span>}
              </div>
            ) },
            { key: 'created', header: '등록', sort: (p) => p.created_at, align: 'right',
              cell: (p) => <span className="text-muted">{relativeTime(p.created_at)}</span> },
          ]}
        />
      </Card>
      <NewPlatformDialog open={open} onClose={() => setOpen(false)}
        onCreated={(p) => { setOpen(false); navigate(`/platforms/${p.id}`) }} />
    </>
  )
}
