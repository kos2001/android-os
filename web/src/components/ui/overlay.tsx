import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Button, cx, Field, Textarea } from './primitives'
import { tr } from '../../lib/i18n'

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
}

export function Dialog({ open, onClose, title, description, children, footer, width = 'max-w-lg' }: {
  open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children?: ReactNode
  footer?: ReactNode; width?: string
}) {
  useEscape(open, onClose)
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 pt-[10vh]">
      <div className="fixed inset-0 animate-fade-in bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div role="dialog" aria-modal="true" className={cx('relative w-full animate-slide-up rounded-xl border border-line bg-surface shadow-pop', width)}>
        <header className="flex items-start justify-between gap-4 px-5 pb-3 pt-4">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
            {description && <p className="mt-1 text-xs text-muted">{description}</p>}
          </div>
          <Button variant="ghost" size="sm" aria-label={tr('닫기', 'Close')} onClick={onClose} icon={<X className="size-4" />} />
        </header>
        {children && <div className="px-5 pb-4">{children}</div>}
        {footer && <footer className="flex justify-end gap-2 border-t border-line bg-page/60 px-5 py-3 rounded-b-xl">{footer}</footer>}
      </div>
    </div>,
    document.body,
  )
}

export function Drawer({ open, onClose, title, subtitle, children, actions }: {
  open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; actions?: ReactNode
}) {
  useEscape(open, onClose)
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 animate-fade-in bg-black/30" onClick={onClose} />
      <aside role="dialog" aria-modal="true" className="absolute inset-y-0 right-0 flex w-full max-w-xl animate-slide-in flex-col border-l border-line bg-surface shadow-pop">
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold text-ink">{title}</h2>
            {subtitle && <div className="mt-1 text-xs text-muted">{subtitle}</div>}
          </div>
          <div className="flex items-center gap-1">
            {actions}
            <Button variant="ghost" size="sm" aria-label={tr('닫기', 'Close')} onClick={onClose} icon={<X className="size-4" />} />
          </div>
        </header>
        <div className="scrollbar-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </aside>
    </div>,
    document.body,
  )
}

/** 되돌리기 어려운 작업 확인. requireReason 이면 사유 입력 필수. */
export function ConfirmDialog({ open, onClose, onConfirm, title, description, confirmLabel, danger, requireReason }: {
  open: boolean; onClose: () => void; onConfirm: (reason: string) => Promise<void> | void; title: string
  description?: ReactNode; confirmLabel: string; danger?: boolean; requireReason?: boolean
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) setReason('') }, [open])
  const confirm = async () => {
    setBusy(true)
    try {
      await onConfirm(reason.trim())
      onClose()
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      footer={<>
        <Button onClick={onClose}>{tr('취소', 'Cancel')}</Button>
        <Button variant={danger ? 'danger' : 'primary'} loading={busy}
          disabled={requireReason && !reason.trim()} onClick={confirm}>{confirmLabel}</Button>
      </>}
    >
      {requireReason && (
        <Field label={tr('사유', 'Reason')} hint={tr('감사 로그에 기록됩니다', 'Recorded in the audit log')}>
          <Textarea autoFocus rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      )}
    </Dialog>
  )
}

// ------------------------------------------------------------------ Toast
type ToastKind = 'success' | 'error' | 'info' | 'warning'
interface Toast { id: number; kind: ToastKind; title: string; description?: string }

const ToastContext = createContext<(t: Omit<Toast, 'id'>) => void>(() => {})

export function useToast() {
  return useContext(ToastContext)
}

const TOAST_ICON: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 className="size-4 text-good" />,
  error: <XCircle className="size-4 text-critical" />,
  warning: <AlertTriangle className="size-4 text-warning" />,
  info: <Info className="size-4 text-accent-ink" />,
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = nextId.current++
    setToasts((prev) => [...prev.slice(-3), { ...t, id }])
    window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), t.kind === 'error' ? 7000 : 3500)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      {createPortal(
        <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
          {toasts.map((t) => (
            <div key={t.id} className="pointer-events-auto flex animate-slide-up gap-2.5 rounded-lg border border-line bg-raised px-3 py-2.5 shadow-pop">
              <span className="mt-0.5">{TOAST_ICON[t.kind]}</span>
              <div className="min-w-0">
                <p className="text-[13px] font-medium text-ink">{t.title}</p>
                {t.description && <p className="mt-0.5 whitespace-pre-wrap break-words text-xs text-muted">{t.description}</p>}
              </div>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}
