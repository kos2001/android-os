import { AppWindow, Bluetooth, Camera, Cpu, HardDrive, Keyboard, MapPin, MemoryStick, Monitor, Nfc, OctagonX,
  Puzzle, Radio, Usb, Volume2, Wifi, Zap, Gauge } from 'lucide-react'
import type { ReactNode } from 'react'
import { Card, CardHeader, cx, EmptyState, ErrorBanner, Mono, Skeleton } from '../components/ui/primitives'
import { Badge } from '../components/ui/status'
import { api, type DriverEntry, type Subsystem } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'

// 서브시스템마다 고유한 색 계열 (라이트: 50 배경 + 700 글자, 다크: 500/10 배경 + 300 글자). 아이콘·이름을 항상 같이 표시한다.
const SUBSYSTEM: Record<Subsystem, { ko: string; en: string; icon: ReactNode; chip: string; bar: string }> = {
  display: { ko: '디스플레이', en: 'Display', icon: <Monitor className="size-4" />, chip: 'bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-500/30', bar: 'bg-sky-500' },
  camera: { ko: '카메라', en: 'Camera', icon: <Camera className="size-4" />, chip: 'bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-500/30', bar: 'bg-violet-500' },
  audio: { ko: '오디오', en: 'Audio', icon: <Volume2 className="size-4" />, chip: 'bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200 dark:bg-fuchsia-500/10 dark:text-fuchsia-300 dark:ring-fuchsia-500/30', bar: 'bg-fuchsia-500' },
  wifi: { ko: 'Wi-Fi', en: 'Wi-Fi', icon: <Wifi className="size-4" />, chip: 'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30', bar: 'bg-emerald-500' },
  bluetooth: { ko: '블루투스', en: 'Bluetooth', icon: <Bluetooth className="size-4" />, chip: 'bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/30', bar: 'bg-blue-500' },
  input: { ko: '입력·터치', en: 'Input & touch', icon: <Keyboard className="size-4" />, chip: 'bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30', bar: 'bg-amber-500' },
  usb: { ko: 'USB', en: 'USB', icon: <Usb className="size-4" />, chip: 'bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-500/15 dark:text-slate-300 dark:ring-slate-500/30', bar: 'bg-slate-500' },
  storage: { ko: '스토리지', en: 'Storage', icon: <HardDrive className="size-4" />, chip: 'bg-orange-50 text-orange-700 ring-orange-200 dark:bg-orange-500/10 dark:text-orange-300 dark:ring-orange-500/30', bar: 'bg-orange-500' },
  power: { ko: '전원·열', en: 'Power & thermal', icon: <Zap className="size-4" />, chip: 'bg-yellow-50 text-yellow-800 ring-yellow-200 dark:bg-yellow-500/10 dark:text-yellow-300 dark:ring-yellow-500/30', bar: 'bg-yellow-500' },
  sensors: { ko: '센서', en: 'Sensors', icon: <Gauge className="size-4" />, chip: 'bg-teal-50 text-teal-700 ring-teal-200 dark:bg-teal-500/10 dark:text-teal-300 dark:ring-teal-500/30', bar: 'bg-teal-500' },
  gnss: { ko: 'GNSS', en: 'GNSS', icon: <MapPin className="size-4" />, chip: 'bg-lime-50 text-lime-800 ring-lime-200 dark:bg-lime-500/10 dark:text-lime-300 dark:ring-lime-500/30', bar: 'bg-lime-500' },
  nfc: { ko: 'NFC', en: 'NFC', icon: <Nfc className="size-4" />, chip: 'bg-pink-50 text-pink-700 ring-pink-200 dark:bg-pink-500/10 dark:text-pink-300 dark:ring-pink-500/30', bar: 'bg-pink-500' },
  network: { ko: '모뎀·네트워크', en: 'Modem & network', icon: <Radio className="size-4" />, chip: 'bg-cyan-50 text-cyan-700 ring-cyan-200 dark:bg-cyan-500/10 dark:text-cyan-300 dark:ring-cyan-500/30', bar: 'bg-cyan-500' },
  memory: { ko: '메모리(DMA-BUF)', en: 'Memory (DMA-BUF)', icon: <MemoryStick className="size-4" />, chip: 'bg-indigo-50 text-indigo-700 ring-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-500/30', bar: 'bg-indigo-500' },
  other: { ko: '기타', en: 'Other', icon: <Puzzle className="size-4" />, chip: 'bg-stone-100 text-stone-700 ring-stone-200 dark:bg-stone-500/15 dark:text-stone-300 dark:ring-stone-500/30', bar: 'bg-stone-400' },
}

function KernelRow({ d }: { d: DriverEntry }) {
  const t = useT()
  return (
    <li className="flex flex-wrap items-center gap-1.5 py-1.5">
      <Cpu className="size-3.5 shrink-0 text-muted" aria-hidden />
      <Mono className="text-ink">{d.name}</Mono>
      {d.buses.map((b) => <Badge key={b}>{b}</Badge>)}
      {d.uses_ion && <Badge tone="critical" icon={<OctagonX className="size-3" />}>ION</Badge>}
      {d.kmi_missing != null && (d.kmi_missing === 0
        ? <Badge tone="good">KMI OK</Badge>
        : <span title={d.kmi_missing_symbols?.join(', ')}><Badge tone="warning">{t(`KMI 누락 ${d.kmi_missing}`, `${d.kmi_missing} KMI missing`)}</Badge></span>)}
      {d.detail && <span className="w-full pl-5 text-[11px] text-muted">{d.detail}</span>}
    </li>
  )
}

function HalRow({ d }: { d: DriverEntry }) {
  return (
    <li className="flex flex-wrap items-center gap-1.5 py-1.5">
      <AppWindow className="size-3.5 shrink-0 text-muted" aria-hidden />
      <Mono className="text-ink">{d.name}</Mono>
      <Badge tone={d.format === 'hidl' ? 'warning' : 'neutral'}>{d.format}{d.version ? ` ${d.version}` : ''}</Badge>
    </li>
  )
}

export default function PlatformDrivers({ platformId, kernelBranch, reloadKey }: {
  platformId: number; kernelBranch: string; reloadKey?: unknown
}) {
  const t = useT()
  const inv = useAsync(() => api.drivers(platformId, kernelBranch || undefined), [platformId, kernelBranch, reloadKey])
  const d = inv.data
  const maxCount = Math.max(1, ...(d?.subsystems ?? []).map((g) => g.kernel.length + g.hal.length))

  return (
    <Card className="mt-4">
      <CardHeader
        title={t('드라이버 인벤토리', 'Driver inventory')}
        description={t('커널 드라이버(vendor .ko)와 HAL 을 서브시스템별로 묶었습니다. 분류는 import 한 커널 API·HAL 이름 기반 추정입니다.',
          'Kernel drivers (vendor .ko) and HALs grouped by subsystem. Grouping is inferred from imported kernel APIs and HAL names.')}
        actions={d && <div className="flex flex-wrap gap-1.5">
          <Badge><Cpu className="size-3" />{t(`커널 드라이버 ${d.totals.kernel}`, `${d.totals.kernel} kernel drivers`)}</Badge>
          <Badge><AppWindow className="size-3" />HAL {d.totals.hal}</Badge>
          {d.totals.hidl > 0 && <Badge tone="warning">HIDL {d.totals.hidl}</Badge>}
          {d.totals.ion_drivers.length > 0 && <Badge tone="critical" icon={<OctagonX className="size-3" />}>
            {t(`ION 사용 ${d.totals.ion_drivers.length}`, `${d.totals.ion_drivers.length} using ION`)}</Badge>}
          <Badge tone={d.kmi_checked ? 'accent' : 'neutral'}>
            {d.kmi_checked ? t(`KMI 기준 ${d.kernel_branch}`, `KMI vs ${d.kernel_branch}`)
              : t(`${d.kernel_branch} symbol list 없음`, `No ${d.kernel_branch} symbol list`)}
          </Badge>
        </div>}
      />
      {inv.error ? <div className="p-4"><ErrorBanner error={inv.error} onRetry={inv.reload} /></div>
        : !d ? <div className="grid gap-3 p-4 md:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}</div>
          : d.subsystems.length === 0 ? (
            <EmptyState icon={<Puzzle className="size-5" />} title={t('드라이버 정보가 없습니다', 'No driver data yet')}
              description={t('커널 카드에서 vendor 모듈(.ko)을, 상단에서 Manifest 를 올리면 서브시스템별로 정리됩니다.',
                'Upload vendor modules (.ko) in the kernel card and a manifest above to see drivers by subsystem.')} />
          ) : (
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
              {d.subsystems.map((g) => {
                const s = SUBSYSTEM[g.subsystem]
                const n = g.kernel.length + g.hal.length
                return (
                  <section key={g.subsystem} className="overflow-hidden rounded-xl border border-line bg-surface">
                    <div className="flex items-center gap-2.5 border-b border-line px-3 py-2.5">
                      <span className={cx('flex size-8 items-center justify-center rounded-lg ring-1 ring-inset', s.chip)}>{s.icon}</span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] font-semibold text-ink">{t(s.ko, s.en)}</p>
                        <div className="mt-1 h-1.5 w-full rounded-full bg-line/60" aria-hidden>
                          <div className={cx('h-1.5 rounded-full', s.bar)} style={{ width: `${(n / maxCount) * 100}%` }} />
                        </div>
                      </div>
                      <span className="text-xs tabular text-muted">{t(`커널 ${g.kernel.length} · HAL ${g.hal.length}`, `kernel ${g.kernel.length} · HAL ${g.hal.length}`)}</span>
                    </div>
                    <ul className="divide-y divide-line px-3">
                      {g.kernel.map((k) => <KernelRow key={`k-${k.name}`} d={k} />)}
                      {g.hal.map((h) => <HalRow key={`h-${h.format}-${h.name}-${h.version}`} d={h} />)}
                    </ul>
                  </section>
                )
              })}
            </div>
          )}
    </Card>
  )
}
