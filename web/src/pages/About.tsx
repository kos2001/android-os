import { ArrowRight, BookOpen, CircuitBoard, Boxes, CheckCircle2, Cpu, Database, FileCode2, FileDiff, Gauge, GitBranch, Globe,
  Layers, Lock, Monitor, OctagonX, PackageCheck, Rocket, ScrollText, ShieldCheck, Smartphone, Sparkles, Upload,
  Workflow } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button, cx } from '../components/ui/primitives'
import { api } from '../lib/api'
import { num } from '../lib/format'
import { navigate, useAsync } from '../lib/hooks'
import { useT } from '../lib/i18n'
import { HUE, type Hue } from '../lib/palette'

// 소개 페이지는 섹션·단계마다 다른 색 계열(lib/palette.ts)을 쓴다. 색만으로 뜻을 전하지 않도록 아이콘·라벨을 함께 둔다.

function IconChip({ hue, children, size = 'md' }: { hue: Hue; children: ReactNode; size?: 'md' | 'lg' }) {
  return (
    <span className={cx('inline-flex shrink-0 items-center justify-center rounded-lg ring-1 ring-inset',
      HUE[hue].soft, HUE[hue].text, HUE[hue].ring, size === 'lg' ? 'size-11' : 'size-9')}>
      {children}
    </span>
  )
}

function Section({ eyebrow, hue, title, lead, children }: {
  eyebrow: string; hue: Hue; title: string; lead?: string; children: ReactNode
}) {
  return (
    <section className="mt-12">
      <p className={cx('text-xs font-semibold uppercase tracking-wider', HUE[hue].text)}>{eyebrow}</p>
      <h2 className="mt-1 text-lg font-semibold tracking-tight text-ink">{title}</h2>
      {lead && <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-ink-2">{lead}</p>}
      <div className="mt-5">{children}</div>
    </section>
  )
}

function Stat({ hue, icon, label, value }: { hue: Hue; icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded-xl bg-white/80 px-4 py-3 shadow-sm ring-1 ring-black/5 backdrop-blur dark:bg-white/5 dark:ring-white/10">
      <IconChip hue={hue}>{icon}</IconChip>
      <div className="min-w-0">
        <p className="text-xl font-semibold tabular text-ink">{value}</p>
        <p className="text-[11px] leading-tight text-muted">{label}</p>
      </div>
    </div>
  )
}

export default function AboutPage() {
  const t = useT()
  const ov = useAsync(() => api.overview().catch(() => undefined), [])
  const d = ov.data
  const sum = (o?: Partial<Record<string, number>>) => Object.values(o ?? {}).reduce<number>((n, v) => n + (v ?? 0), 0)

  const pillars: { hue: Hue; icon: ReactNode; title: string; body: string; points: string[]; href: string; cta: string }[] = [
    {
      hue: 'sky', icon: <ShieldCheck className="size-5" />, href: '/platforms', cta: t('플랫폼 판정하기', 'Check a platform'),
      title: t('업그레이드 준비도 (Readiness)', 'Upgrade readiness'),
      body: t('SoC·BSP 플랫폼 프로파일을 목표 Android 릴리스와 비교해, 업그레이드를 막는 문제를 Blocker·Warning·Info 로 판정합니다.',
        'Compares an SoC/BSP platform profile with the target Android release and classifies what stands in the way as Blocker, Warning or Info.'),
      points: [
        t('커널 호환·EOL·KMI 심볼, VINTF HAL, ION·VNDK·16KB·sepolicy 규칙', 'Kernel compatibility, EOL and KMI symbols, VINTF HALs, ION/VNDK/16KB/sepolicy rules'),
        t('모든 판정에 1차 출처 링크와 지식베이스 버전 기록', 'Every finding links its primary source and records the knowledge base version'),
        t('Blocker·Warning 은 담당자·상태가 있는 작업 항목이 됨', 'Blockers and warnings become work items with owners and status'),
      ],
    },
    {
      hue: 'orange', icon: <Rocket className="size-5" />, href: '/rollouts', cta: t('롤아웃 보기', 'View rollouts'),
      title: t('OTA 배포 (Delivery)', 'OTA delivery'),
      body: t('서명된 A/B OTA 패키지를 등록·검사하고, 기기에 맞는 패키지를 골라 단계적으로 배포하며 이상이 보이면 자동으로 멈춥니다.',
        'Registers and inspects signed A/B OTA packages, picks the right package per device, rolls it out in stages and halts automatically when something looks wrong.'),
      points: [
        t('수 GB 패키지를 HTTP Range 로 수백 KB 만 읽어 검증', 'Validates multi-GB packages by reading only a few hundred KB over HTTP Range'),
        t('incremental 우선·full 폴백, 다운그레이드·SPL 하락 차단', 'Prefers incremental, falls back to full, blocks downgrades and SPL rollbacks'),
        t('단계별 soak 시간, 오류율·부팅 폴백율 기반 자동 중단', 'Per-stage soak time and auto-halt on error or boot-fallback rates'),
      ],
    },
  ]

  const steps: { hue: Hue; icon: ReactNode; title: string; body: string }[] = [
    { hue: 'sky', icon: <Cpu className="size-4" />, title: t('플랫폼 등록', 'Register a platform'),
      body: t('SoC, 현재 Android 버전, 커널 브랜치, 지원 종료 목표일', 'SoC, current Android version, kernel branch, support end date') },
    { hue: 'violet', icon: <Upload className="size-4" />, title: t('산출물 업로드', 'Upload artifacts'),
      body: t('VINTF manifest, uname -r, 커널 config, vendor 모듈(.ko)', 'VINTF manifest, uname -r, kernel config, vendor modules (.ko)') },
    { hue: 'emerald', icon: <Gauge className="size-4" />, title: t('준비도 판정', 'Run a readiness check'),
      body: t('목표 릴리스·계획 커널 기준으로 규칙 평가', 'Rules evaluated against the target release and planned kernel') },
    { hue: 'amber', icon: <ScrollText className="size-4" />, title: t('작업 항목 처리', 'Work the items'),
      body: t('담당자 지정, 진행·완료·면제(사유 필수)', 'Assign owners; in progress, done or waived (reason required)') },
    { hue: 'rose', icon: <PackageCheck className="size-4" />, title: t('패키지 등록', 'Register packages'),
      body: t('payload·metadata·해시 검증 후 ready 또는 거부 사유', 'Payload, metadata and hashes verified → ready or rejected with reasons') },
    { hue: 'teal', icon: <Rocket className="size-4" />, title: t('단계 배포', 'Staged rollout'),
      body: t('1% → 10% → 100%, 지표 확인 후 승격·중단', '1% → 10% → 100%, promote or halt based on metrics') },
  ]

  const checks: { hue: Hue; icon: ReactNode; title: string; body: string }[] = [
    { hue: 'indigo', icon: <GitBranch className="size-4" />, title: t('커널', 'Kernel'),
      body: t('GKI 호환 매트릭스, QPR 지원 중단, ACK EOL, uprev 권장 브랜치', 'GKI compatibility matrix, QPR drops, ACK EOL, recommended uprev branch') },
    { hue: 'fuchsia', icon: <FileCode2 className="size-4" />, title: t('KMI 심볼', 'KMI symbols'),
      body: t('vendor 모듈이 쓰는 심볼 × 목표 브랜치 symbol list', 'Symbols used by vendor modules × target branch symbol list') },
    { hue: 'violet', icon: <FileDiff className="size-4" />, title: 'VINTF / HAL',
      body: t('FCM 레벨 제거, manifest × compatibility matrix, HIDL 잔존', 'Removed FCM levels, manifest × compatibility matrix, remaining HIDL') },
    { hue: 'rose', icon: <OctagonX className="size-4" />, title: t('폐지된 기능', 'Removed features'),
      body: t('ION(DMA-BUF heaps 로 이전), VNDK(Android 15+)', 'ION (move to DMA-BUF heaps), VNDK (Android 15+)') },
    { hue: 'lime', icon: <Layers className="size-4" />, title: t('16 KB 페이지', '16 KB pages'),
      body: t('커널 config 로 페이지 크기 확인, prebuilt 정렬 점검', 'Page size from kernel config, prebuilt alignment checks') },
    { hue: 'teal', icon: <CircuitBoard className="size-4" />, title: t('드라이버', 'Drivers'),
      body: t('커널 드라이버·HAL 서브시스템별 인벤토리, 드라이버별 ION 사용·KMI 누락', 'Kernel drivers and HALs by subsystem; per-driver ION use and missing KMI symbols') },
    { hue: 'amber', icon: <Lock className="size-4" />, title: 'SELinux',
      body: t('Android 17 memfd_class / memfd_file 대응', 'Android 17 memfd_class / memfd_file readiness') },
  ]

  const arch: { hue: Hue; icon: ReactNode; title: string; body: string }[] = [
    { hue: 'sky', icon: <Monitor className="size-4" />, title: t('웹 콘솔', 'Web console'),
      body: t('React · 한국어/English · 라이트/다크', 'React · Korean/English · light/dark') },
    { hue: 'violet', icon: <Workflow className="size-4" />, title: 'Backend API',
      body: t('FastAPI · /admin/v1 (역할 기반) · /device/v1 (기기 키)', 'FastAPI · /admin/v1 (role-based) · /device/v1 (device keys)') },
    { hue: 'emerald', icon: <Sparkles className="size-4" />, title: 'upgrade_core',
      body: t('표준 라이브러리만: OTA·VINTF·커널 파서, 매칭, 롤아웃 판정', 'Standard library only: OTA/VINTF/kernel parsers, matching, rollout logic') },
    { hue: 'amber', icon: <Database className="size-4" />, title: t('저장소', 'Storage'),
      body: t('SQLite (운영 전환 시 PostgreSQL), 감사 로그', 'SQLite (PostgreSQL for production), audit log') },
  ]

  const sources: { hue: Hue; icon: ReactNode; title: string; body: string }[] = [
    { hue: 'teal', icon: <BookOpen className="size-4" />, title: 'AOSP',
      body: t('compatibility matrix, KMI symbol list 가져오기', 'Compatibility matrices and KMI symbol lists') },
    { hue: 'orange', icon: <Globe className="size-4" />, title: t('OTA 오리진', 'OTA origins'),
      body: t('허용 목록 호스트의 Range 지원 https', 'Range-capable https on allow-listed hosts') },
    { hue: 'rose', icon: <Smartphone className="size-4" />, title: t('기기', 'Devices'),
      body: t('update-check·설치 이벤트 → update_engine', 'update-check and install events → update_engine') },
  ]

  return (
    <div className="pb-8">
      {/* 히어로: 여러 색의 그라디언트 배경 + 실시간 요약 */}
      <div className="relative overflow-hidden rounded-2xl border border-line p-6 md:p-10">
        <div aria-hidden className="absolute inset-0 bg-gradient-to-br from-sky-100 via-violet-100 to-rose-100 dark:from-sky-500/15 dark:via-violet-500/15 dark:to-rose-500/15" />
        <div aria-hidden className="absolute -right-16 -top-16 size-64 rounded-full bg-amber-200/60 blur-3xl dark:bg-amber-500/15" />
        <div aria-hidden className="absolute -bottom-20 left-1/3 size-72 rounded-full bg-emerald-200/60 blur-3xl dark:bg-emerald-500/10" />
        <div className="relative">
          <p className="inline-flex items-center gap-1.5 rounded-full bg-white/80 px-3 py-1 text-[11px] font-medium text-violet-700 ring-1 ring-violet-200 dark:bg-white/10 dark:text-violet-300 dark:ring-violet-500/30">
            <Sparkles className="size-3.5" />{t('Android 플랫폼 OS 업그레이드', 'Android platform OS upgrades')}
          </p>
          <h1 className="mt-4 max-w-3xl text-2xl font-bold tracking-tight text-ink md:text-4xl">
            {t('업그레이드 준비부터 ', 'From upgrade readiness ')}
            <span className="bg-gradient-to-r from-sky-600 via-violet-600 to-rose-600 bg-clip-text text-transparent dark:from-sky-300 dark:via-violet-300 dark:to-rose-300">
              {t('OTA 단계 배포까지', 'to staged OTA rollout')}
            </span>
          </h1>
          <p className="mt-3 max-w-2xl text-[14px] leading-relaxed text-ink-2">
            {t('Android 기기·BSP 를 새 메이저 버전(예: 16 → 17)으로 올릴 때, 무엇이 막고 있는지 근거와 함께 보여 주고 서명된 업데이트를 안전하게 나눠 배포하는 서비스입니다.',
              'When moving Android devices and BSPs to a new major release (e.g. 16 → 17), this service shows what is blocking the upgrade — with sources — and delivers signed updates safely, in stages.')}
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Button variant="primary" icon={<ShieldCheck className="size-3.5" />} onClick={() => navigate('/platforms')}>
              {t('플랫폼 판정 시작', 'Start a readiness check')}
            </Button>
            <Button icon={<Boxes className="size-3.5" />} onClick={() => navigate('/packages')}>{t('OTA 패키지', 'OTA packages')}</Button>
            <Button icon={<BookOpen className="size-3.5" />} onClick={() => navigate('/knowledge')}>{t('릴리스 지식베이스', 'Release knowledge base')}</Button>
          </div>
          <div className="mt-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat hue="sky" icon={<Cpu className="size-4" />} label={t('등록 플랫폼', 'Platforms')} value={d ? num(d.platforms.length) : '—'} />
            <Stat hue="rose" icon={<ScrollText className="size-4" />} label={t('미해결 작업 항목', 'Open work items')} value={d ? num(sum(d.open_work_items)) : '—'} />
            <Stat hue="emerald" icon={<PackageCheck className="size-4" />} label={t('OTA 패키지', 'OTA packages')} value={d ? num(sum(d.packages)) : '—'} />
            <Stat hue="amber" icon={<Rocket className="size-4" />} label={t('롤아웃', 'Rollouts')} value={d ? num(sum(d.rollouts)) : '—'} />
          </div>
        </div>
      </div>

      <Section eyebrow={t('두 가지 축', 'Two pillars')} hue="violet" title={t('이 서비스가 하는 일', 'What this service does')}>
        <div className="grid gap-4 lg:grid-cols-2">
          {pillars.map((p) => (
            <div key={p.href} className="relative overflow-hidden rounded-xl border border-line bg-surface p-5">
              <div aria-hidden className={cx('absolute inset-x-0 top-0 h-1 bg-gradient-to-r', HUE[p.hue].bar)} />
              <div className="flex items-start gap-3">
                <IconChip hue={p.hue} size="lg">{p.icon}</IconChip>
                <div>
                  <h3 className="text-[15px] font-semibold text-ink">{p.title}</h3>
                  <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{p.body}</p>
                </div>
              </div>
              <ul className="mt-4 space-y-2">
                {p.points.map((pt) => (
                  <li key={pt} className="flex gap-2 text-[13px] text-ink-2">
                    <CheckCircle2 className={cx('mt-0.5 size-4 shrink-0', HUE[p.hue].text)} />{pt}
                  </li>
                ))}
              </ul>
              <button onClick={() => navigate(p.href)}
                className={cx('mt-5 inline-flex items-center gap-1 text-[13px] font-medium hover:underline', HUE[p.hue].text)}>
                {p.cta}<ArrowRight className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      </Section>

      <Section eyebrow={t('사용 흐름', 'How it works')} hue="emerald" title={t('6단계로 끝나는 업그레이드', 'An upgrade in six steps')}
        lead={t('왼쪽 세 단계는 준비도, 오른쪽 세 단계는 배포입니다. 각 단계는 콘솔 화면이나 API 호출 하나에 해당합니다.',
          'The first three steps cover readiness, the last three cover delivery. Each step maps to one console screen or API call.')}>
        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {steps.map((s, i) => (
            <li key={s.title} className={cx('relative rounded-xl p-4 ring-1 ring-inset', HUE[s.hue].soft, HUE[s.hue].ring)}>
              <div className="flex items-center justify-between">
                <span className={cx('flex size-7 items-center justify-center rounded-full text-[12px] font-bold text-white shadow-sm', HUE[s.hue].solid)}>
                  {i + 1}
                </span>
                <span className={HUE[s.hue].text}>{s.icon}</span>
              </div>
              <p className={cx('mt-3 text-[13px] font-semibold', HUE[s.hue].text)}>{s.title}</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-2">{s.body}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section eyebrow={t('판정 규칙', 'What gets checked')} hue="fuchsia" title={t('준비도 판정이 보는 것', 'What a readiness check looks at')}
        lead={t('공개 1차 출처로 확인된 사실만 Blocker 로 판정합니다. 확인되지 않은 항목은 Warning·Info 로 남겨 사람이 결정하게 합니다.',
          'Only facts confirmed by public primary sources can be Blockers. Anything unconfirmed stays a Warning or Info for a person to decide.')}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {checks.map((c) => (
            <div key={c.title} className="flex gap-3 rounded-xl border border-line bg-surface p-4">
              <IconChip hue={c.hue}>{c.icon}</IconChip>
              <div>
                <p className="text-[13px] font-semibold text-ink">{c.title}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-ink-2">{c.body}</p>
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section eyebrow={t('구성', 'Architecture')} hue="sky" title={t('어떻게 만들어져 있나', 'How it is built')}>
        <div className="grid gap-4 lg:grid-cols-[1fr_auto_1fr] lg:items-center">
          <ol className="space-y-2">
            {arch.map((a, i) => (
              <li key={a.title}>
                <div className={cx('flex items-center gap-3 rounded-xl p-3 ring-1 ring-inset', HUE[a.hue].soft, HUE[a.hue].ring)}>
                  <IconChip hue={a.hue}>{a.icon}</IconChip>
                  <div className="min-w-0">
                    <p className={cx('text-[13px] font-semibold', HUE[a.hue].text)}>{a.title}</p>
                    <p className="text-xs text-ink-2">{a.body}</p>
                  </div>
                </div>
                {i < arch.length - 1 && <div aria-hidden className="ml-7 h-2 w-px bg-line" />}
              </li>
            ))}
          </ol>
          <div aria-hidden className="hidden items-center gap-1 text-muted lg:flex">
            <span className="h-px w-8 bg-line" /><ArrowRight className="size-4" />
          </div>
          <div className="rounded-xl border border-dashed border-line p-4">
            <p className="text-xs font-medium text-muted">{t('외부 연결', 'External connections')}</p>
            <ul className="mt-3 space-y-3">
              {sources.map((s) => (
                <li key={s.title} className="flex items-center gap-3">
                  <IconChip hue={s.hue}>{s.icon}</IconChip>
                  <div>
                    <p className="text-[13px] font-semibold text-ink">{s.title}</p>
                    <p className="text-xs text-ink-2">{s.body}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section eyebrow={t('원칙', 'Principles')} hue="rose" title={t('설계 원칙', 'Design principles')}>
        <div className="grid gap-3 md:grid-cols-3">
          {[
            { hue: 'teal' as Hue, icon: <BookOpen className="size-4" />, title: t('근거 우선', 'Evidence first'),
              body: t('판정마다 출처 URL, 지식베이스 버전, 기준일을 남깁니다.', 'Every finding keeps its source URL, knowledge base version and as-of date.') },
            { hue: 'indigo' as Hue, icon: <Lock className="size-4" />, title: t('기본은 닫힘', 'Fail closed'),
              body: t('키·허용 호스트가 없으면 서버가 시작을 거부합니다. 모든 변경은 감사 로그에 남습니다.', 'The server refuses to start without keys and allowed hosts. Every change is audit-logged.') },
            { hue: 'orange' as Hue, icon: <OctagonX className="size-4" />, title: t('안전한 배포', 'Safe delivery'),
              body: t('기존 대상 기기를 유지하는 해시 버킷, 부팅 폴백 감지, 임계값 기반 자동 중단.', 'Stable hash buckets, boot-fallback detection and threshold-based auto-halt.') },
          ].map((p) => (
            <div key={p.title} className={cx('rounded-xl p-4 ring-1 ring-inset', HUE[p.hue].soft, HUE[p.hue].ring)}>
              <p className={cx('flex items-center gap-2 text-[13px] font-semibold', HUE[p.hue].text)}>{p.icon}{p.title}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-ink-2">{p.body}</p>
            </div>
          ))}
        </div>
      </Section>

      <div className="mt-12 flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-gradient-to-r from-violet-600 via-sky-600 to-emerald-600 p-6 text-white">
        <div>
          <p className="text-[15px] font-semibold">{t('지금 첫 플랫폼을 판정해 보세요', 'Check your first platform now')}</p>
          <p className="mt-1 text-[13px] text-white/85">
            {t('API 문서는 /docs (OpenAPI) 에서 볼 수 있습니다.', 'API documentation is available at /docs (OpenAPI).')}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => navigate('/platforms')}
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-white px-3.5 text-[13px] font-medium text-violet-700 shadow-sm hover:bg-white/90">
            <Cpu className="size-4" />{t('플랫폼으로', 'Go to platforms')}
          </button>
          <a href="/docs" target="_blank" rel="noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-white/15 px-3.5 text-[13px] font-medium text-white ring-1 ring-inset ring-white/40 hover:bg-white/25">
            <FileCode2 className="size-4" />API /docs
          </a>
        </div>
      </div>
    </div>
  )
}
