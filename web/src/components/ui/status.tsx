import { AlertOctagon, AlertTriangle, Archive, CheckCircle2, CircleDashed, CircleDot, Info, OctagonX,
  PauseCircle, PlayCircle, RotateCcw, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import type { AssignmentState, OtaPackage, RolloutState, Severity, WorkStatus } from '../../lib/api'
import { localizedRecord, tr } from '../../lib/i18n'
import { HUE, hueOf, type Hue } from '../../lib/palette'
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

/** tone 은 상태(성공·경고·위험), hue 는 장식용 색 구분(채널·버스·형식 등). hue 가 있으면 hue 를 쓴다. */
export function Badge({ tone = 'neutral', hue, icon, children, className }: {
  tone?: Tone; hue?: Hue; icon?: ReactNode; children: ReactNode; className?: string
}) {
  const color = hue ? cx(HUE[hue].soft, HUE[hue].text, HUE[hue].ring) : TONES[tone]
  return (
    <span className={cx('inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full px-2 text-[11px] font-medium ring-1 ring-inset',
      color, className)}>
      {icon}
      {children}
    </span>
  )
}

const I = 'size-3'

const ROLLOUT: Record<RolloutState, [Tone, ReactNode, [string, string]]> = {
  draft: ['neutral', <CircleDashed className={I} />, ['초안', 'Draft']],
  active: ['accent', <PlayCircle className={I} />, ['진행 중', 'Active']],
  paused: ['warning', <PauseCircle className={I} />, ['일시정지', 'Paused']],
  halted: ['critical', <OctagonX className={I} />, ['중단됨', 'Halted']],
  completed: ['good', <CheckCircle2 className={I} />, ['완료', 'Completed']],
}

export function RolloutBadge({ state }: { state: RolloutState }) {
  const [tone, icon, label] = ROLLOUT[state]
  return <Badge tone={tone} icon={icon}>{tr(...label)}</Badge>
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

export const WORK_STATUS_LABEL: Record<WorkStatus, string> = localizedRecord({
  todo: ['할 일', 'To do'], in_progress: ['진행 중', 'In progress'], done: ['완료', 'Done'], waived: ['면제', 'Waived'],
})

export function ReadyBadge({ ready }: { ready: boolean | null | undefined }) {
  if (ready == null) return <Badge icon={<CircleDashed className={I} />}>{tr('미판정', 'Not evaluated')}</Badge>
  return ready
    ? <Badge tone="good" icon={<CheckCircle2 className={I} />}>{tr('업그레이드 가능', 'Ready')}</Badge>
    : <Badge tone="critical" icon={<AlertOctagon className={I} />}>{tr('Blocker 있음', 'Has blockers')}</Badge>
}

export const ASSIGNMENT_LABEL: Record<AssignmentState, string> = localizedRecord({
  offered: ['제공됨', 'Offered'],
  downloading: ['다운로드 중', 'Downloading'],
  installed_pending_reboot: ['재부팅 대기', 'Pending reboot'],
  boot_success: ['부팅 성공', 'Boot success'],
  boot_fallback: ['부팅 폴백', 'Boot fallback'],
  failed: ['설치 실패', 'Install failed'],
})

const CHANNEL_HUE: Record<string, Hue> = { testing: 'amber', beta: 'violet', stable: 'emerald' }

export function ChannelBadge({ channel }: { channel: string }) {
  return <Badge hue={CHANNEL_HUE[channel] ?? hueOf(channel)} icon={<CircleDot className={I} />}>{channel}</Badge>
}

export function RetryIcon() {
  return <RotateCcw className={I} />
}
