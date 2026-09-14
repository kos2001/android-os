// backend/app.py · backend/ota_api.py 응답 타입과 호출 래퍼

export type Severity = 'blocker' | 'warning' | 'info'
export type WorkStatus = 'todo' | 'in_progress' | 'done' | 'waived'
export type RolloutState = 'draft' | 'active' | 'paused' | 'halted' | 'completed'
export type AssignmentState =
  | 'offered' | 'downloading' | 'installed_pending_reboot' | 'boot_success' | 'boot_fallback' | 'failed'
export type Channel = 'testing' | 'beta' | 'stable'

export interface Platform {
  id: number
  name: string
  soc: string
  android_version: string
  kernel_branch: string
  fcm_target_level: string | null
  uses_vndk: boolean
  uses_ion: boolean
  supports_16kb: boolean
  sepolicy_memfd_ready: boolean
  support_until: string | null
  created_at: string
  manifest: { target_level: string | null; hal_count: number; uploaded_at: string } | null
}

export interface Finding {
  id: number
  rule_id: string
  severity: Severity
  title: string
  detail: string
  sources: string[]
  work_item_id: number | null
  status: WorkStatus | null
  owner: string | null
  waive_reason: string | null
  external_ref: string | null
}

export interface ReadinessRun {
  id: number
  platform_id: number
  target_release: string
  kb_version: string
  created_by: string
  created_at: string
  ready: boolean
  counts: Record<Severity, number>
  as_of: string
  current_release: string
  findings: Finding[]
  hal_check?: string
}

export interface RunSummary {
  id: number
  target_release: string
  kb_version: string
  created_by: string
  created_at: string
}

export interface KbRelease {
  release: string
  api_level: number | string
  fcm_level?: string
  fcm_level_confidence?: string
  released?: string
  status?: string
  supported_kernels: string[]
  kernels_unsupported_from?: Record<string, string>
  vndk_supported?: boolean
  ion_supported?: boolean
  latest_cts?: string
  fcm_matrices_in_tree?: string[]
  sources: string[]
}

export interface KernelBranch {
  branch: string
  launch: string
  eol: string
}

export interface KnowledgeBase {
  kb_version: string
  releases: KbRelease[]
  kernel_branches: KernelBranch[]
}

export interface MatrixDiff {
  old_level: string
  new_level: string
  added: string[]
  removed: string[]
  changed: {
    hal: string
    versions_before: string[]
    versions_after: string[]
    interfaces_added: string[]
    interfaces_removed: string[]
  }[]
}

export interface OtaPackage {
  id: number
  type: 'full' | 'incremental'
  device: string
  post_build: string
  pre_device: string[]
  pre_builds: string[]
  post_timestamp: number
  post_spl: string
  wipe: boolean
  downgrade: boolean
  spl_downgrade: boolean
  url: string
  file_size: number
  sha256: string | null
  payload_offset: number
  payload_size: number
  payload_properties: Record<string, string>
  streaming_property_files: string
  status: 'ready' | 'rejected' | 'retired'
  reject_reasons: string[]
  created_by: string
  created_at: string
}

export interface InspectResult {
  ready: boolean
  package_type: 'full' | 'incremental'
  pre_device: string[]
  pre_builds: string[]
  post_build: string
  post_timestamp: number
  post_spl: string
  post_sdk_level: number | null
  wipe: boolean
  payload_offset: number
  payload_size: number
  file_size: number
  reject_reasons: string[]
  apply_payload_headers: string[]
  range_requests: number | null
  bytes_fetched: number | null
}

export interface Stage {
  seq: number
  percent: number
  min_soak_hours: number
  promoted_at: string | null
  promoted_by: string | null
}

export interface HaltRules {
  min_sample: number
  max_error_rate: number | null
  max_boot_fallback_rate: number | null
  max_error_code_rate: Record<string, number>
  window_minutes: number | null
}

export interface Policy {
  require_unmetered: boolean
  min_battery_pct: number
  install_window: string | null
  switch_slot_on_reboot: boolean
  mandatory: boolean
  check_interval_s: number
  max_attempts: number
}

export interface Rollout {
  id: number
  name: string
  device: string
  target_fingerprint: string
  channel: Channel
  filters: Record<string, string[]>
  state: RolloutState
  current_stage: number
  current_percent: number
  halt_rules: HaltRules
  halt_mode: 'stop_new' | 'stop_all_pending'
  halt_reason: string | null
  policy: Policy
  created_by: string
  created_at: string
  stages: Stage[]
  assignments?: Partial<Record<AssignmentState, number>>
}

export interface RolloutWindow {
  attempted: number
  failed_by_code: Record<string, number>
  installed: number
  boot_fallback: number
}

export interface RolloutMetrics {
  rollout_id: number
  assignments: Partial<Record<AssignmentState, number>>
  window: RolloutWindow
  errors: { code: number; name: string; devices: number }[]
}

export interface TimePoint {
  hour: string
  download_started: number
  updated_need_reboot: number
  boot_success: number
}

export interface HaltEvaluation {
  rollout_id: number
  state: RolloutState
  halt: boolean
  halted_now: boolean
  reasons: string[]
  window: RolloutWindow
}

export interface DeltaReport {
  target_fingerprint: string
  device: string
  window_days: number
  active_devices_not_on_target: number
  sources: { fingerprint: string; devices: number; share: number; has_incremental: boolean }[]
}

export interface AuditEntry {
  id: number
  actor: string
  action: string
  entity: string
  entity_id: number | null
  before: string | null
  after: string | null
  at: string
}

export interface Overview {
  platforms: (Pick<Platform, 'id' | 'name' | 'soc' | 'android_version' | 'kernel_branch'> & {
    latest_run: null | { id: number; target_release: string; created_at: string; ready: boolean; counts: Record<Severity, number> }
  })[]
  open_work_items: Partial<Record<Severity, number>>
  packages: Partial<Record<OtaPackage['status'], number>>
  rollouts: Partial<Record<RolloutState, number>>
  devices_checked_in_24h: number
  boot_success_24h: number
  boot_fallback_24h: number
  install_failures_24h: number
  kb_version: string
  dev_mode: boolean
}

export interface Health {
  status: string
  version: string
  kb_version: string
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

const KEY_STORAGE = 'apiKey'

export function getApiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) ?? ''
  } catch {
    return ''
  }
}

export function setApiKey(key: string) {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key)
    else localStorage.removeItem(KEY_STORAGE)
  } catch {
    /* 저장 불가 환경 — 세션 동안만 입력값 사용 불가 */
  }
}

function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const b = body as { error?: { message?: string }; detail?: unknown }
    if (b.error?.message) return b.error.message
    if (typeof b.detail === 'string') return b.detail
    if (Array.isArray(b.detail)) {
      return b.detail
        .map((d: { loc?: (string | number)[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`)
        .join('\n')
    }
  }
  return `HTTP ${status}`
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  const key = getApiKey()
  if (key) headers.Authorization = `Bearer ${key}`
  let payload: BodyInit | undefined
  if (body instanceof FormData) {
    payload = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(path, { method, headers, body: payload })
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) throw new ApiError(res.status, errorMessage(res.status, data))
  return data as T
}

const get = <T,>(path: string) => request<T>('GET', path)
const post = <T,>(path: string, body?: unknown) => request<T>('POST', path, body)

export const api = {
  health: () => get<Health>('/api/health'),
  overview: () => get<Overview>('/admin/v1/overview'),
  kb: () => get<KnowledgeBase>('/admin/v1/kb/releases'),

  platforms: () => get<Platform[]>('/admin/v1/platforms'),
  platform: (id: number) => get<Platform>(`/admin/v1/platforms/${id}`),
  createPlatform: (body: Partial<Platform>) => post<Platform>('/admin/v1/platforms', body),
  uploadManifest: (id: number, files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<{ platform: Platform; hal_instances_by_format: Record<string, number>; hals: string[] }>(
      'PUT', `/admin/v1/platforms/${id}/manifest`, form)
  },
  runs: (id: number) => get<RunSummary[]>(`/admin/v1/platforms/${id}/readiness-runs`),
  createRun: (id: number, target_release: string) =>
    post<ReadinessRun>(`/admin/v1/platforms/${id}/readiness-runs`, { target_release }),
  run: (runId: number) => get<ReadinessRun>(`/admin/v1/readiness-runs/${runId}`),
  patchWorkItem: (id: number, body: Partial<Pick<Finding, 'status' | 'owner' | 'waive_reason' | 'external_ref'>>) =>
    request<unknown>('PATCH', `/admin/v1/work-items/${id}`, body),

  matrices: () => get<{ release: string; level: string; source: string | null; uploaded_at: string }[]>('/admin/v1/matrices'),
  matrixDiff: (oldFile: File, newFile: File) => {
    const form = new FormData()
    form.append('old', oldFile)
    form.append('new', newFile)
    return post<MatrixDiff>('/admin/v1/vintf/matrix-diff', form)
  },

  packages: () => get<OtaPackage[]>('/admin/v1/packages'),
  inspectPackage: (url: string) => post<InspectResult>('/admin/v1/packages/inspect', { url }),
  registerPackage: (url: string, sha256?: string) =>
    post<OtaPackage>('/admin/v1/packages', sha256 ? { url, sha256 } : { url }),
  retirePackage: (id: number) => post<OtaPackage>(`/admin/v1/packages/${id}/retire`),

  rollouts: () => get<Rollout[]>('/admin/v1/rollouts'),
  rollout: (id: number) => get<Rollout>(`/admin/v1/rollouts/${id}`),
  createRollout: (body: unknown) => post<Rollout>('/admin/v1/rollouts', body),
  transition: (id: number, action: string, reason?: string) =>
    post<Rollout>(`/admin/v1/rollouts/${id}/${action}`, reason ? { reason } : undefined),
  metrics: (id: number) => get<RolloutMetrics>(`/admin/v1/rollouts/${id}/metrics`),
  timeseries: (id: number, hours = 48) => get<TimePoint[]>(`/admin/v1/rollouts/${id}/timeseries?hours=${hours}`),
  evaluateHalt: (id: number, apply = false) =>
    post<HaltEvaluation>(`/admin/v1/rollouts/${id}/evaluate-halt?apply=${apply}`),
  deltaCandidates: (target: string, days: number) =>
    get<DeltaReport>(`/admin/v1/reports/delta-candidates?target_fingerprint=${encodeURIComponent(target)}&days=${days}`),

  audit: (entity?: string) => get<AuditEntry[]>(`/admin/v1/audit?limit=300${entity ? `&entity=${entity}` : ''}`),
}
