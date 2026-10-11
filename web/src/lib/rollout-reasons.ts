import { tr } from './i18n'

const REASONS: Record<string, [string, string]> = {
  ELIGIBLE: ['제공 대상', 'Eligible'], FILTER_MISMATCH: ['태그·속성 불일치', 'Tags or attributes do not match'],
  NOT_IN_ROLLOUT: ['현재 배포 비율 밖', 'Outside current percentage'], UP_TO_DATE: ['대상 빌드 사용 중', 'Already on target build'],
  NO_COMPATIBLE_PACKAGE: ['호환 패키지 없음', 'No compatible package'], ROLLOUT_HALTED: ['롤아웃 중단됨', 'Rollout halted'],
  ROLLOUT_INACTIVE: ['롤아웃 비활성', 'Rollout inactive'], PENDING_REBOOT: ['재부팅 대기', 'Pending reboot'],
  RETRY_LIMIT_REACHED: ['최대 재시도 초과', 'Retry limit reached'], NOT_ACTIVE: ['진행 중인 롤아웃 필요', 'Rollout must be active'],
  FINAL_STAGE: ['마지막 단계', 'Final stage'], SOAK_PENDING: ['최소 유지 시간 대기', 'Waiting for soak time'],
  INSUFFICIENT_SUCCESSFUL_BOOTS: ['부팅 성공 표본 부족', 'Not enough successful boots'],
  SUCCESS_RATE_BELOW_THRESHOLD: ['성공률 기준 미달', 'Success rate below threshold'],
}

export function rolloutReason(reason: string): string {
  const label = REASONS[reason]
  return label ? tr(...label) : reason
}
