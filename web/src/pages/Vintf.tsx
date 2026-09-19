import { FileDiff, FileUp, Minus, Plus } from 'lucide-react'
import { useState } from 'react'
import { PageHeader, StatTile } from '../components/layout'
import { useToast } from '../components/ui/overlay'
import { Button, Card, CardHeader, EmptyState, Mono } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { DataTable } from '../components/ui/table'
import { api, type MatrixDiff } from '../lib/api'
import { dateTime } from '../lib/format'
import { useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'

function FilePick({ label, file, onPick }: { label: string; file: File | null; onPick: (f: File | null) => void }) {
  const t = useT()
  return (
    <label className="flex flex-1 cursor-pointer items-center gap-3 rounded-lg border border-dashed border-line bg-page px-4 py-3 transition hover:border-accent">
      <FileUp className="size-5 text-muted" />
      <div className="min-w-0">
        <p className="text-xs text-muted">{label}</p>
        <p className="truncate text-[13px] font-medium text-ink">{file?.name ?? t('compatibility_matrix.*.xml 선택', 'Choose compatibility_matrix.*.xml')}</p>
      </div>
      <input type="file" accept=".xml" className="hidden" onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
    </label>
  )
}

export default function VintfPage() {
  const toast = useToast()
  const t = useT()
  const matrices = useAsync(() => api.matrices(), [])
  const [oldFile, setOld] = useState<File | null>(null)
  const [newFile, setNew] = useState<File | null>(null)
  const [diff, setDiff] = useState<MatrixDiff>()
  const [busy, setBusy] = useState(false)

  const compare = async () => {
    if (!oldFile || !newFile) return
    setBusy(true)
    try {
      setDiff(await api.matrixDiff(oldFile, newFile))
    } catch (e) {
      toast({ kind: 'error', title: t('비교 실패', 'Compare failed'), description: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title={t('VINTF 비교', 'VINTF compare')}
        description={t('두 framework compatibility matrix 를 비교해 추가·제거·버전 범위가 바뀐 HAL 을 찾습니다. AOSP main 이 아닌 릴리스 태그의 파일을 사용하세요.',
          'Compare two framework compatibility matrices to find HALs that were added, removed, or changed version range. Use files from a release tag, not AOSP main.')} />
      <Card className="mb-4">
        <div className="flex flex-col gap-3 p-4 md:flex-row md:items-center">
          <FilePick label={t('이전 (예: android-16 202504)', 'Before (e.g. android-16 202504)')} file={oldFile} onPick={setOld} />
          <FilePick label={t('이후 (예: android-17 202604)', 'After (e.g. android-17 202604)')} file={newFile} onPick={setNew} />
          <Button variant="primary" icon={<FileDiff className="size-4" />} loading={busy} disabled={!oldFile || !newFile} onClick={compare}>{t('비교', 'Compare')}</Button>
        </div>
      </Card>

      {diff ? (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <StatTile label={t(`추가 (level ${diff.new_level})`, `Added (level ${diff.new_level})`)} value={diff.added.length} icon={<Plus className="size-3.5" />} />
            <StatTile label={t(`제거 (level ${diff.old_level} 대비)`, `Removed (vs level ${diff.old_level})`)} value={diff.removed.length} icon={<Minus className="size-3.5" />} />
            <StatTile label={t('버전·인터페이스 변경', 'Version/interface changes')} value={diff.changed.length} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader title={t('제거된 HAL', 'Removed HALs')} description={t('이 레벨로 올리면 기기가 더 이상 제공하면 안 되거나 프레임워크가 쓰지 않음', 'At this level the device should no longer provide these, or the framework no longer uses them')} />
              <ul className="divide-y divide-line">{diff.removed.length ? diff.removed.map((h) => (
                <li key={h} className="flex items-center gap-2 px-4 py-2"><Badge tone="critical">{t('제거', 'Removed')}</Badge><Mono>{h}</Mono></li>
              )) : <li className="px-4 py-6 text-center text-xs text-muted">{t('없음', 'None')}</li>}</ul>
            </Card>
            <Card>
              <CardHeader title={t('추가된 HAL', 'Added HALs')} />
              <ul className="divide-y divide-line">{diff.added.length ? diff.added.map((h) => (
                <li key={h} className="flex items-center gap-2 px-4 py-2"><Badge tone="good">{t('추가', 'Added')}</Badge><Mono>{h}</Mono></li>
              )) : <li className="px-4 py-6 text-center text-xs text-muted">{t('없음', 'None')}</li>}</ul>
            </Card>
          </div>
          <Card>
            <CardHeader title={t('변경된 HAL', 'Changed HALs')} />
            <DataTable rows={diff.changed} rowKey={(c) => c.hal} searchText={(c) => c.hal} searchPlaceholder={t('HAL 이름 검색', 'Search HAL name')}
              columns={[
                { key: 'hal', header: 'HAL', sort: (c) => c.hal, cell: (c) => <Mono>{c.hal}</Mono> },
                { key: 'before', header: t('이전', 'Before'), cell: (c) => <Mono className="text-muted">{c.versions_before.join(', ')}</Mono> },
                { key: 'after', header: t('이후', 'After'), cell: (c) => <Mono className="font-semibold">{c.versions_after.join(', ')}</Mono> },
                { key: 'if', header: t('인터페이스', 'Interfaces'), cell: (c) => (
                  <span className="text-xs">
                    {c.interfaces_added.map((i) => <Badge key={i} tone="good" className="mr-1">+{i}</Badge>)}
                    {c.interfaces_removed.map((i) => <Badge key={i} tone="critical" className="mr-1">−{i}</Badge>)}
                    {!c.interfaces_added.length && !c.interfaces_removed.length && <span className="text-muted">—</span>}
                  </span>) },
              ]} />
          </Card>
        </div>
      ) : (
        <Card>
          <EmptyState icon={<FileDiff className="size-5" />} title={t('비교할 두 파일을 선택하세요', 'Choose two files to compare')}
            description={t('판정에 쓰는 matrix 는 scripts/import_matrices.py 로 AOSP 릴리스 태그에서 가져올 수 있습니다.',
              'Matrices used for checks can be imported from AOSP release tags with scripts/import_matrices.py.')} />
        </Card>
      )}

      <Card className="mt-4">
        <CardHeader title={t('등록된 matrix', 'Registered matrices')} description={t('준비도 판정에서 HAL 단위 검사에 사용', 'Used for per-HAL checks in readiness runs')} />
        <DataTable rows={matrices.data} loading={matrices.loading} rowKey={(m) => `${m.release}-${m.level}`}
          empty={<p className="py-8 text-center text-xs text-muted">{t('등록된 matrix 가 없습니다', 'No matrices registered')}</p>}
          columns={[
            { key: 'release', header: t('릴리스', 'Release'), sort: (m) => m.release, cell: (m) => `Android ${m.release}` },
            { key: 'level', header: t('레벨', 'Level'), sort: (m) => Number(m.level), cell: (m) => <span className="tabular">{m.level}</span> },
            { key: 'source', header: t('출처', 'Source'), cell: (m) => m.source
              ? <a href={m.source} target="_blank" rel="noreferrer" className="break-all text-xs text-accent-ink hover:underline">{m.source}</a>
              : <span className="text-muted">—</span> },
            { key: 'at', header: t('등록', 'Registered'), align: 'right', cell: (m) => <span className="text-muted">{dateTime(m.uploaded_at)}</span> },
          ]} />
      </Card>
    </>
  )
}
