import { ScrollText } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '../components/layout'
import { Drawer } from '../components/ui/overlay'
import { Card, cx, EmptyState, ErrorBanner, KeyValue, Segmented } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api, type AuditEntry } from '../lib/api'
import { dateTime, relativeTime } from '../lib/format'
import { useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'
import { HUE, hueOf, type Hue } from '../lib/palette'

const ENTITIES = ['all', 'platform', 'readiness_run', 'work_item', 'fcm_matrix', 'ota_package', 'rollout', 'device'] as const

// 장식용 색 구분 — 뜻이 비슷한 동작은 비슷한 색 (생성=초록, 업로드=보라 계열, 롤아웃 진행=파랑 계열). halt 는 상태 톤(critical)을 그대로 쓴다.
const ACTION_HUE: Record<string, Hue> = {
  create: 'emerald', register: 'teal', update: 'sky', retire: 'slate', set_tags: 'blue',
  upload_manifest: 'indigo', upload_kernel: 'violet', upload_symbol_list: 'purple', upload_matrix: 'fuchsia',
  start: 'cyan', promote: 'blue', pause: 'amber', resume: 'lime', complete: 'emerald',
}
const ENTITY_HUE: Record<string, Hue> = {
  platform: 'indigo', readiness_run: 'teal', work_item: 'amber', fcm_matrix: 'fuchsia',
  ota_package: 'emerald', rollout: 'orange', device: 'blue', kmi_symbol_list: 'purple',
}
const actionHue = (a: string) => ACTION_HUE[a] ?? hueOf(a)
const entityHue = (e: string) => ENTITY_HUE[e] ?? hueOf(e)

function ActionBadge({ action }: { action: string }) {
  return action === 'halt' ? <Badge tone="critical">{action}</Badge> : <Badge hue={actionHue(action)}>{action}</Badge>
}

function EntityBadge({ entity, id }: { entity: string; id?: number | null }) {
  return <Badge hue={entityHue(entity)} className="font-mono">{entity}{id != null ? ` #${id}` : ''}</Badge>
}

function Actor({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden className={cx('flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold uppercase text-white', HUE[hueOf(name)].solid)}>
        {name.charAt(0) || '?'}
      </span>
      <span className="font-medium">{name}</span>
    </span>
  )
}

function pretty(json: string | null) {
  if (!json) return '—'
  try {
    return JSON.stringify(JSON.parse(json), null, 2)
  } catch {
    return json
  }
}

export default function AuditPage() {
  const t = useT()
  const [entity, setEntity] = useState<(typeof ENTITIES)[number]>('all')
  const log = useAsync(() => api.audit(entity === 'all' ? undefined : entity), [entity])
  const [selected, setSelected] = useState<AuditEntry | null>(null)

  return (
    <>
      <PageHeader title={t('감사 로그', 'Audit log')} description={t('플랫폼·판정·패키지·롤아웃·기기 태그의 변경 기록 (최근 300건).', 'Changes to platforms, checks, packages, rollouts and device tags (latest 300).')} />
      {log.error && <div className="mb-4"><ErrorBanner error={log.error} onRetry={log.reload} /></div>}
      <Card>
        <DataTable
          rows={log.data}
          loading={log.loading}
          rowKey={(a) => a.id}
          onRowClick={setSelected}
          searchText={(a) => `${a.actor} ${a.action} ${a.entity} ${a.after ?? ''}`}
          searchPlaceholder={t('행위자, 동작, 내용 검색', 'Search actor, action, details')}
          toolbar={<Segmented value={entity} onChange={setEntity} items={ENTITIES.map((e) => ({ value: e, label: e === 'all' ? t('전체', 'All') : (
            <span className="inline-flex items-center gap-1.5"><span aria-hidden className={cx('size-1.5 rounded-full', HUE[entityHue(e)].dot)} />{e}</span>
          ) }))} />}
          empty={<EmptyState icon={<ScrollText className="size-5" />} title={t('기록이 없습니다', 'No records')} />}
          columns={[
            { key: 'at', header: t('시각', 'Time'), sort: (a) => a.at, cell: (a) => <span title={dateTime(a.at)} className="text-ink-2">{relativeTime(a.at)}</span> },
            { key: 'actor', header: t('행위자', 'Actor'), sort: (a) => a.actor, cell: (a) => <Actor name={a.actor} /> },
            { key: 'action', header: t('동작', 'Action'), sort: (a) => a.action, cell: (a) => <ActionBadge action={a.action} /> },
            { key: 'entity', header: t('대상', 'Target'), cell: (a) => <EntityBadge entity={a.entity} id={a.entity_id} /> },
            { key: 'summary', header: t('내용', 'Details'), cell: (a) => <span className="line-clamp-1 max-w-md text-xs text-muted">{a.after ?? ''}</span> },
          ]}
        />
      </Card>
      <Drawer open={!!selected} onClose={() => setSelected(null)} title={selected ? `${selected.action} · ${selected.entity}` : ''}
        subtitle={selected && `${selected.actor} · ${dateTime(selected.at)}`}>
        {selected && (
          <div className="space-y-4">
            <KeyValue items={[['ID', selected.id], [t('행위자', 'Actor'), <Actor name={selected.actor} />], [t('동작', 'Action'), <ActionBadge action={selected.action} />],
              [t('대상', 'Target'), <EntityBadge entity={selected.entity} id={selected.entity_id} />]]} />
            {(['before', 'after'] as const).map((k) => (
              <section key={k}>
                <h3 className="mb-2 text-xs font-medium text-muted">{k === 'before' ? t('변경 전', 'Before') : t('변경 후', 'After')}</h3>
                <pre className="scrollbar-thin overflow-x-auto rounded-md bg-page p-3 font-mono text-[11.5px] text-ink">{pretty(selected[k])}</pre>
              </section>
            ))}
          </div>
        )}
      </Drawer>
    </>
  )
}
