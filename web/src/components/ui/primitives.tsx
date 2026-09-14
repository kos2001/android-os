import { Check, Copy, Loader2 } from 'lucide-react'
import { forwardRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode,
  type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-accent text-white border-accent hover:brightness-110 shadow-sm',
  secondary: 'bg-raised text-ink border-line hover:bg-page shadow-sm',
  ghost: 'border-transparent text-ink-2 hover:bg-line/50 hover:text-ink',
  danger: 'bg-critical text-white border-critical hover:brightness-110 shadow-sm',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, icon, className, children, disabled, ...rest }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cx(
        'inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-md border font-medium',
        'transition-[background,filter,color] duration-100 disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-[13px]',
        VARIANTS[variant], className)}
      {...rest}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" /> : icon}
      {children}
    </button>
  )
})

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cx('rounded-lg border border-line bg-surface', className)}>{children}</section>
}

export function CardHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}

const inputBase =
  'rounded-md border border-line bg-raised px-2.5 text-[13px] text-ink placeholder:text-muted ' +
  'outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60'

/** 폭 클래스를 넘기면 기본 w-full 을 쓰지 않는다 (같은 속성 유틸리티 충돌 방지). */
const width = (className?: string) => (/(^|\s)(w-|min-w-|flex-1)/.test(className ?? '') ? '' : 'w-full')

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest }, ref) {
  return <input ref={ref} className={cx(inputBase, width(className), 'h-8', className)} {...rest} />
})

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cx(inputBase, width(className), 'h-8 pr-7', className)} {...rest}>{children}</select>
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cx(inputBase, width(className), 'py-2', className)} {...rest} />
}

export function Field({ label, hint, error, children, className }: {
  label: ReactNode; hint?: ReactNode; error?: string; children: ReactNode; className?: string
}) {
  return (
    <label className={cx('block', className)}>
      <span className="mb-1 block text-xs font-medium text-ink-2">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-xs text-critical">{error}</span>
        : hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  )
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 py-1">
      <span className="text-[13px] text-ink-2">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx('relative h-5 w-9 rounded-full transition', checked ? 'bg-accent' : 'bg-line')}
      >
        <span className={cx('absolute top-0.5 size-4 rounded-full bg-white shadow transition-all',
          checked ? 'left-[18px]' : 'left-0.5')} />
      </button>
    </label>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-line bg-raised px-1 font-sans text-[10px] font-medium text-muted">
      {children}
    </kbd>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse rounded bg-line/60', className)} />
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx('size-4 animate-spin text-muted', className)} />
}

export function EmptyState({ icon, title, description, action }: {
  icon: ReactNode; title: string; description?: ReactNode; action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 flex size-10 items-center justify-center rounded-full border border-line bg-raised text-muted">
        {icon}
      </div>
      <p className="text-[13px] font-semibold text-ink">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorBanner({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start justify-between gap-3 rounded-md border border-critical/30 bg-critical/5 px-3 py-2.5 text-[13px]">
      <span className="whitespace-pre-wrap text-ink">
        <b className="font-semibold text-critical">오류</b> · {error.message}
      </span>
      {onRetry && <Button size="sm" variant="ghost" onClick={onRetry}>다시 시도</Button>}
    </div>
  )
}

export function CopyButton({ value, label }: { value: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <Button
      size="sm"
      variant="ghost"
      aria-label={label ?? '복사'}
      icon={done ? <Check className="size-3.5 text-good" /> : <Copy className="size-3.5" />}
      onClick={(e) => {
        e.stopPropagation()
        navigator.clipboard?.writeText(value).then(() => {
          setDone(true)
          window.setTimeout(() => setDone(false), 1200)
        })
      }}
    >
      {label}
    </Button>
  )
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx('font-mono text-[12px]', className)}>{children}</span>
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(120px,max-content)_1fr] gap-x-6 gap-y-2 text-[13px]">
      {items.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Tabs<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode; count?: number }[]
}) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-line">
      {items.map((item) => (
        <button
          key={item.value}
          role="tab"
          aria-selected={value === item.value}
          onClick={() => onChange(item.value)}
          className={cx('-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium transition',
            value === item.value ? 'border-accent text-ink' : 'border-transparent text-muted hover:text-ink')}
        >
          {item.label}
          {item.count != null && (
            <span className="tabular rounded-full bg-line/70 px-1.5 text-[11px] text-ink-2">{item.count}</span>
          )}
        </button>
      ))}
    </div>
  )
}

export function Segmented<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode }[]
}) {
  return (
    <div className="inline-flex rounded-md border border-line bg-page p-0.5">
      {items.map((item) => (
        <button
          key={item.value}
          onClick={() => onChange(item.value)}
          className={cx('h-6 rounded px-2.5 text-xs font-medium transition',
            value === item.value ? 'bg-raised text-ink shadow-sm' : 'text-muted hover:text-ink')}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
