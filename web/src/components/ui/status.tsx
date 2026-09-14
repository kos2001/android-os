import { AlertOctagon, AlertTriangle, Archive, CheckCircle2, CircleDashed, CircleDot, Info, OctagonX,
  PauseCircle, PlayCircle, RotateCcw, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import type { AssignmentState, OtaPackage, RolloutState, Severity, WorkStatus } from '../../lib/api'
import { cx } from './primitives'

// 상태는 색만으로 전달하지 않는다 — 항상 아이콘 + 라벨 (dataviz 상태 팔레트 규칙)
type Tone = 'good' | 'warning' | 'serious' | 'critical' | 'accent' | 'neutral'

const TONES: Record<Tone, string> = {
  good: 'bg-good/10 text-[#006300] dark:text-good ring-good/25',
  warning: 'bg-warning/15 text-[#8a5a00] dark:text-warning ring-warning/30',
  serious: 'bg-serious/15 text-[#a4461f] dark:text-serious ring-serious/30',
  critical: 'bg-critical/10 text-critical dark:text-[#e66767] ring-critical/25',
  accent: 'bg-accent/10 text-accent-ink ring-accent/25',
  neutral: 'bg-line/50 text-ink-2 ring-line',
}

export function Badge({ tone = 'neutral', icon, children, className }: {
  tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string
}) {
  return (
    <span className={cx('inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full px-2 text-[11px] font-medium ring-1 ring-inset',
      TONES[tone], className)}>
      {icon}
      {children}
    </span>
  )
}

const I = 'size-3'

const ROLLOUT: Record<RolloutState, [Tone, ReactNode, string]> = {
  draft: ['neutral', <CircleDashed className={I} />, '초안'],
  active: ['accent', <PlayCircle className={I} />, '진행 중'],
  paused: ['warning', <PauseCircle className={I} />, '일시정지'],
  halted: ['critical', <OctagonX className={I} />, '중단됨'],
  completed: ['good', <CheckCircle2 className={I} />, '완료'],
}

export function RolloutBadge({ state }: { state: RolloutState }) {
  const [tone, icon, label] = ROLLOUT[state]
  return <Badge tone={tone} icon={icon}>{label}</Badge>
}

const PACKAGE: Record<OtaPackage['status'], [Tone, ReactNode, string]> = {
  ready: ['good', <CheckCircle2 className={I} />, 'Ready'],
  rejected: ['critical', <XCircle className={I} />, 'Rejected'],
  retired: ['neutral', <Archive className={I} />, 'Retired'],
}

export function PackageBadge({ status }: { status: OtaPackage['status'] }) {
  const [tone, icon, label] = PACKAGE[status]
  return <Badge tone={tone} icon={icon}>{label}</Badge>
}

const SEVERITY: Record<Severity, [Tone, ReactNode, string]> = {
  blocker: ['critical', <AlertOctagon className={I} />, 'Blocker'],
  warning: ['warning', <AlertTriangle className={I} />, 'Warning'],
  info: ['neutral', <Info className={I} />, 'Info'],
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const [tone, icon, label] = SEVERITY[severity]
  return <Badge tone={tone} icon={icon}>{label}</Badge>
}

export const WORK_STATUS_LABEL: Record<WorkStatus, string> = {
  todo: '할 일', in_progress: '진행 중', done: '완료', waived: '면제',
}

export function ReadyBadge({ ready }: { ready: boolean | null | undefined }) {
  if (ready == null) return <Badge icon={<CircleDashed className={I} />}>미판정</Badge>
  return ready
    ? <Badge tone="good" icon={<CheckCircle2 className={I} />}>업그레이드 가능</Badge>
    : <Badge tone="critical" icon={<AlertOctagon className={I} />}>Blocker 있음</Badge>
}

export const ASSIGNMENT_LABEL: Record<AssignmentState, string> = {
  offered: '제공됨',
  downloading: '다운로드 중',
  installed_pending_reboot: '재부팅 대기',
  boot_success: '부팅 성공',
  boot_fallback: '부팅 폴백',
  failed: '설치 실패',
}

export function ChannelBadge({ channel }: { channel: string }) {
  return <Badge icon={<CircleDot className={I} />}>{channel}</Badge>
}

export function RetryIcon() {
  return <RotateCcw className={I} />
}
