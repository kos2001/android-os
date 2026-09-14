import { ScrollText } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '../components/layout'
import { Drawer } from '../components/ui/overlay'
import { Card, EmptyState, ErrorBanner, KeyValue, Mono, Segmented } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api, type AuditEntry } from '../lib/api'
import { dateTime, relativeTime } from '../lib/format'
import { useAsync } from '../lib/hooks'

const ENTITIES = ['all', 'platform', 'readiness_run', 'work_item', 'fcm_matrix', 'ota_package', 'rollout'] as const

function pretty(json: string | null) {
  if (!json) return '—'
  try {
    return JSON.stringify(JSON.parse(json), null, 2)
  } catch {
    return json
  }
}

export default function AuditPage() {
  const [entity, setEntity] = useState<(typeof ENTITIES)[number]>('all')
  const log = useAsync(() => api.audit(entity === 'all' ? undefined : entity), [entity])
  const [selected, setSelected] = useState<AuditEntry | null>(null)

  return (
    <>
      <PageHeader title="감사 로그" description="플랫폼·판정·패키지·롤아웃의 모든 변경 기록 (최근 300건)." />
      {log.error && <div className="mb-4"><ErrorBanner error={log.error} onRetry={log.reload} /></div>}
      <Card>
        <DataTable
          rows={log.data}
          loading={log.loading}
          rowKey={(a) => a.id}
          onRowClick={setSelected}
          searchText={(a) => `${a.actor} ${a.action} ${a.entity} ${a.after ?? ''}`}
          searchPlaceholder="행위자, 동작, 내용 검색"
          toolbar={<Segmented value={entity} onChange={setEntity} items={ENTITIES.map((e) => ({ value: e, label: e === 'all' ? '전체' : e }))} />}
          empty={<EmptyState icon={<ScrollText className="size-5" />} title="기록이 없습니다" />}
          columns={[
            { key: 'at', header: '시각', sort: (a) => a.at, cell: (a) => <span title={dateTime(a.at)} className="text-ink-2">{relativeTime(a.at)}</span> },
            { key: 'actor', header: '행위자', sort: (a) => a.actor, cell: (a) => <span className="font-medium">{a.actor}</span> },
            { key: 'action', header: '동작', sort: (a) => a.action, cell: (a) => <Badge tone={a.action === 'halt' ? 'critical' : 'neutral'}>{a.action}</Badge> },
            { key: 'entity', header: '대상', cell: (a) => <Mono>{a.entity}{a.entity_id != null ? ` #${a.entity_id}` : ''}</Mono> },
            { key: 'summary', header: '내용', cell: (a) => <span className="line-clamp-1 max-w-md text-xs text-muted">{a.after ?? ''}</span> },
          ]}
        />
      </Card>
      <Drawer open={!!selected} onClose={() => setSelected(null)} title={selected ? `${selected.action} · ${selected.entity}` : ''}
        subtitle={selected && `${selected.actor} · ${dateTime(selected.at)}`}>
        {selected && (
          <div className="space-y-4">
            <KeyValue items={[['ID', selected.id], ['대상', `${selected.entity} #${selected.entity_id ?? '—'}`]]} />
            {(['before', 'after'] as const).map((k) => (
              <section key={k}>
                <h3 className="mb-2 text-xs font-medium text-muted">{k === 'before' ? '변경 전' : '변경 후'}</h3>
                <pre className="scrollbar-thin overflow-x-auto rounded-md bg-page p-3 font-mono text-[11.5px] text-ink">{pretty(selected[k])}</pre>
              </section>
            ))}
          </div>
        )}
      </Drawer>
    </>
  )
}
