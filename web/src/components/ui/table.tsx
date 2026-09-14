import { ArrowDown, ArrowUp, ChevronsUpDown, Search } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { cx, Input, Skeleton } from './primitives'

export interface Column<T> {
  key: string
  header: ReactNode
  cell: (row: T) => ReactNode
  sort?: (row: T) => string | number
  align?: 'left' | 'right'
  width?: string
  className?: string
}

/** 정렬·검색·행 클릭을 지원하는 목록 표. */
export function DataTable<T>({ rows, columns, rowKey, onRowClick, loading, searchText, searchPlaceholder, empty,
  toolbar, initialSort }: {
  rows: T[] | undefined
  columns: Column<T>[]
  rowKey: (row: T) => string | number
  onRowClick?: (row: T) => void
  loading?: boolean
  searchText?: (row: T) => string
  searchPlaceholder?: string
  empty?: ReactNode
  toolbar?: ReactNode
  initialSort?: { key: string; dir: 'asc' | 'desc' }
}) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState(initialSort)

  const visible = useMemo(() => {
    let out = rows ?? []
    if (query && searchText) {
      const q = query.toLowerCase()
      out = out.filter((r) => searchText(r).toLowerCase().includes(q))
    }
    const col = columns.find((c) => c.key === sort?.key)
    if (col?.sort && sort) {
      const get = col.sort
      out = [...out].sort((a, b) => {
        const va = get(a)
        const vb = get(b)
        const cmp = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb))
        return sort.dir === 'asc' ? cmp : -cmp
      })
    }
    return out
  }, [rows, query, sort, columns, searchText])

  return (
    <div>
      {(searchText || toolbar) && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          {searchText && (
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={searchPlaceholder ?? '검색'}
                className="pl-8" />
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">{toolbar}</div>
        </div>
      )}
      <div className="scrollbar-thin overflow-x-auto">
        <table className="w-full border-collapse text-left text-[13px]">
          <thead>
            <tr className="border-b border-line">
              {columns.map((c) => {
                const active = sort?.key === c.key
                return (
                  <th key={c.key} style={{ width: c.width }}
                    className={cx('h-9 whitespace-nowrap px-3 text-xs font-medium text-muted', c.align === 'right' && 'text-right')}>
                    {c.sort ? (
                      <button
                        className={cx('inline-flex items-center gap-1 hover:text-ink', active && 'text-ink')}
                        onClick={() => setSort({ key: c.key, dir: active && sort?.dir === 'asc' ? 'desc' : 'asc' })}
                      >
                        {c.header}
                        {active ? (sort?.dir === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)
                          : <ChevronsUpDown className="size-3 opacity-40" />}
                      </button>
                    ) : c.header}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {loading && !rows ? (
              Array.from({ length: 4 }).map((_, i) => (
                <tr key={i} className="border-b border-line last:border-0">
                  {columns.map((c) => <td key={c.key} className="px-3 py-3"><Skeleton className="h-3.5 w-3/4" /></td>)}
                </tr>
              ))
            ) : visible.length === 0 ? (
              <tr><td colSpan={columns.length}>{empty ?? <p className="py-10 text-center text-muted">결과가 없습니다</p>}</td></tr>
            ) : (
              visible.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cx('border-b border-line transition-colors last:border-0',
                    onRowClick && 'cursor-pointer hover:bg-page')}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={cx('px-3 py-2.5 align-middle', c.align === 'right' && 'tabular text-right', c.className)}>
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
