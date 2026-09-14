# Android 플랫폼 OS 버전 업그레이드 요구사항 조사 (Android 13 → 17)

- 작성일: 2026-09-14 (환경 기준 날짜)
- 대상: SoC/BSP 벤더, 디바이스 제조사 (Android 15 → 16 → 17 업그레이드)
- 방법: source.android.com, developer.android.com, android-developers.googleblog.com 1차 출처를 WebSearch/WebFetch로 확인. 2차 출처(언론 등)만 있는 항목은 `[2차]`, 1차/2차 모두 확인 못한 항목은 **(미확인)**, 모델 사전지식에 의존한 항목은 `[사전지식]`으로 표기.
- 신뢰도 표기: `[1차]` = 1차 출처에서 직접 확인 / `[2차]` = 언론·커뮤니티 출처 / `[사전지식]` = 조사 중 재확인하지 못함 / **(미확인)** = 추정 또는 근거 불충분

> 주의: WebFetch는 페이지를 요약 모델로 읽기 때문에 세부 표현이 원문과 약간 다를 수 있습니다. 계약/인증 판단에는 반드시 원문(및 파트너 전용 VSR/GMS 문서)을 재확인하십시오.

---

## 0. 핵심 요약 (Executive Summary)

| 항목 | 내용 | 신뢰도 |
|---|---|---|
| 최신 정식 릴리스 | Android 17 (API 37), 2026-06-16 출시, 같은 날 AOSP 공개 | [1차] |
| Android 17 AOSP 태그 | `android-17.0.0_r1`, Build ID `CP2A.260605.016` | [1차] |
| Android 17 기본 SPL | AOSP 기본 security patch level `2026-07-01` | [1차] |
| Android 17 QPR1 | Beta 진행(QPR1 Beta 9: 2026-08), 2026-09-14 기준 정식 미발표 | [2차] |
| AOSP 소스 공개 정책 | 2026년부터 Q2, Q4 연 2회 공개 (보안 패치는 월별 유지) | [1차] |
| Minor SDK | Android 16 QPR2 = API 36.1 (2025-12-02), 최초 minor SDK | [1차] |
| Android 17 GKI | `android17-6.18` (launch 2025-11-30, EOL 2030-07-01) | [1차] |
| Android 17 QPR1 이후 | `android12-5.10`, `android13-5.10` 커널 미지원 | [1차] |
| ION | 모든 Android 버전에서 미지원 (ION 지원 커널 2025-12 EOL) | [1차] |
| AOSP 소스 트리 | Android 17부터 read-only (빌드 설정 수정 필요) | [1차] |
| Play targetSdk | 2026-08-31부터 신규 앱/업데이트 API 36 이상 | [1차: Play/Developers] |

---

## 1. 릴리스 타임라인, API 레벨, 보안 패치, AOSP 공개 정책

### 1.1 버전별 표

| 버전 | 내부 코드네임 | API 레벨 | CTS 버전 | Quarterly release name | 정식 출시일 | 신뢰도 |
|---|---|---|---|---|---|---|
| Android 13 | Tiramisu | 33 | 13 | - | 2022-08-15 | API/CTS [1차], 코드네임·날짜 [사전지식] |
| Android 14 | UpsideDownCake | 34 | 14 | - | 2023-10-04 | API/CTS [1차], 코드네임·날짜 [사전지식] |
| Android 15 | VanillaIceCream | 35 | 15 | 24Q3 | 2024-09-03 (AOSP) | API/CTS/Q명 [1차], 코드네임·날짜 [사전지식] |
| Android 16 | Baklava | 36 | 16 | 25Q2 | 2025-06-10 | API/날짜 [1차], 코드네임 [사전지식] |
| Android 16 QPR2 | - | 36.1 | 16.1 | 25Q4 | 2025-12-02 | [1차] |
| Android 17 | Cinnamon Bun | 37 | 17 | 26Q2 | 2026-06-16 | API/날짜 [1차], 코드네임 [2차] |
| Android 17 QPR1 | - | 37.1 (Beta) | (미확인) | 26Q3 (미확인) | 2026-09-14 기준 미출시 | [1차: developer.android.com에 37.1 Beta 표기], 출시 상태 [2차] |
| Android 17 QPR2 | - | 37.2 (Beta) | (미확인) | 26Q4 (미확인) | 예정 (미확인) | [1차: 37.1→37.2 API diff 표기] |

참고:
- build-numbers 표에는 Android 16 QPR1 행이 없으며, Android 16 최신 AOSP 태그는 `android-16.0.0_r4` / `BP4A.251205.006` (2025-12-05, QPR2 계열)로 표기됨 [1차]. QPR1(2025-09) 소스 공개 여부는 **(미확인)**.
- Android 17 AOSP: `android-17.0.0_r1` / `CP2A.260605.016` / 2026-06-05 태그 날짜 [1차].
- 코드네임 체계: 공식 build-numbers 표에서 Android 15 이후 codename 칸은 "Android15/16/17"로 표기되며 dessert 이름은 공개 문서에 표기되지 않음 [1차]. dessert 이름은 내부/언론 명칭.

### 1.2 Trunk-stable 및 Minor SDK 모델
- Android 16부터 major 릴리스를 Q2로 앞당기고, Q4에 minor SDK 릴리스를 배포. Minor 릴리스는 새 API/기능/최적화는 포함하나 **앱에 영향을 주는 behavior change는 제외**(major에만 포함) [1차: Android 16 블로그].
- Android 16 QPR2(API 36.1)가 최초 minor SDK 릴리스 [1차: Android 16 QPR2 블로그].
- 분기 릴리스 명칭은 `25Q2`, `25Q4`, `26Q2` 형식 [1차: build-numbers].
- AOSP 동기화용 manifest 브랜치로 `android-latest-release` 사용 권고 — "always reference the most recent release pushed to AOSP" [1차: Android 15 release notes / build-numbers].

### 1.3 AOSP 소스 공개 정책 변경 (검증 완료)
- 원문: "Effective in 2026, to align with our trunk stable development model and ensure platform stability for the ecosystem, we will publish source code to AOSP in Q2 and Q4." [1차: build-numbers, GKI release builds 페이지 배너]
- 발표 시점: 2026-01-06경 사이트 배너로 공지 [2차: Android Authority, Droid-Life].
- 보안 패치: 월별 보안 패치는 기존처럼 보안 전용 브랜치에 공개 [2차: PiunikaWeb, TechRadar 보도 — Google 확인 인용].
- BSP 영향: Q1/Q3 QPR의 소스를 AOSP에서 받을 수 없으므로 파트너 채널(Google 파트너 포털/SoC 벤더 경유)에 의존하거나 Q2/Q4 기준으로 업그레이드 계획을 세워야 함 (분석).

### 1.4 보안 패치 레벨(SPL)
- Android Security Bulletin은 월별 발행, SPL은 `YYYY-MM-01`/`YYYY-MM-05` 형식 [사전지식].
- Android 17 AOSP 기본 SPL = `2026-07-01`; Android 17 보안 릴리스 노트는 2026-06-16 발행, 2026-09-03 갱신 [1차].
- GKI 릴리스 빌드는 매월 브랜치로 SPL과 태그를 제공 (예: `android17-6.18-2026-09_r1`, 2026-09-10) [1차].

---

## 2. GKI / 커널

### 2.1 ACK(Android Common Kernel) 브랜치, 출시일, EOL [1차: android-common]

| ACK 브랜치 | Launch date | 지원 기간 | EOL |
|---|---|---|---|
| android12-5.10 | 2020-12-13 | 6년 | 2027-07-01 |
| android13-5.10 | 2020-12-13 | 6년 | 2027-07-01 |
| android13-5.15 | 2021-10-31 | 6년 | 2028-07-01 |
| android14-5.15 | 2021-10-31 | 6년 | 2028-07-01 |
| android14-6.1 | 2022-12-11 | 6년 | 2029-07-01 |
| android15-6.6 | 2023-10-29 | 4년 | 2028-07-01 |
| android16-6.12 | 2024-11-17 | 4년 | 2029-07-01 |
| android17-6.18 | 2025-11-30 | 4년 | 2030-07-01 |

주의: android15-6.6부터 지원 기간이 6년 → 4년으로 단축됨. android15-6.6은 android14-6.1보다 먼저 EOL(2028-07 vs 2029-07) [1차].

### 2.2 플랫폼 버전별 호환 커널 매트릭스 [1차]

| 플랫폼 | 호환(지원) 커널 |
|---|---|
| Android 13 (2022) | android13-5.15, android13-5.10, android12-5.10 |
| Android 14 (2023) | android14-6.1, android14-5.15, android13-5.15, android13-5.10, android12-5.10 |
| Android 15 (2024) | android15-6.6, android14-6.1, android14-5.15, android13-5.15, android13-5.10, android12-5.10 |
| Android 16 (2025) | android16-6.12, android15-6.6, android14-6.1, android14-5.15, android13-5.15, android13-5.10, android12-5.10 |
| Android 17 (2026) | android17-6.18, android16-6.12, android15-6.6, android14-6.1, android14-5.15, android13-5.15, android13-5.10 (*), android12-5.10 (*) |

(*) "not supported in Android 17 QPR1 or higher" [1차].

규칙 [1차]:
- 플랫폼은 이전 릴리스의 GKI 커널과 하위 호환 (예: android14-6.1을 Android 15에서 사용 가능).
- GKI 커널은 자신이 만들어진 릴리스 **이후** 릴리스에서만 지원 (android15-6.6은 Android 14에서 미지원).
- Launch 커널: 신규 출시 디바이스는 해당 릴리스 또는 직전 GKI 사용 (문서 예: Android 15 launch = android15-6.6 또는 android14-6.1) [1차]. Android 16/17의 launch 커널 허용 목록 원문은 **(미확인)** — 동일 규칙이면 Android 17 launch = android17-6.18 / android16-6.12로 추정 **(미확인)**.
- Longevity GRF 조건: 3년 후 major 커널 업그레이드 필요 [2차: Android Authority].

### 2.3 KMI (Kernel Module Interface) [1차]
- KMI frozen 단계: 심각한 보안 이슈 외 KMI-breaking 변경 불허.
- 불가피한 변경 시 `build.config.common`의 KMI generation number 증가 → vendor 모듈 재빌드 필요.
- 인증 GKI 빌드는 파트너 요청 respin을 최대 6개월 지원, 이후에는 ASB 보안 패치 목적 respin만 가능.

### 2.4 android17-6.18 릴리스 빌드 현황 [1차]

| 브랜치 | 커널 버전 | 최신 빌드 | Respin 종료 | Deprecation |
|---|---|---|---|---|
| android17-6.18-2026-06 | 6.18.21 | r1~r19+ (2026-06-18 ~ 07-10) | 2027-01-01 | 2027-10-01 |
| android17-6.18-2026-09 | 6.18.32 | `android17-6.18-2026-09_r1` (2026-09-10) | 2027-01-01 | 2028-01-01 |

### 2.5 16 KB 페이지 크기 [1차: 16kb 문서]
- Android 15부터 AOSP가 16 KB 페이지 빌드 지원. arm64 + 16 KB 커널에서만, `android14-6.1` 이상.
- 커널: Kleaf `--page_size=16k` 또는 `CONFIG_ARM64_16K_PAGES`.
- 플랫폼 빌드 플래그: `PRODUCT_NO_BIONIC_PAGE_SIZE_MACRO := true`, `PRODUCT_MAX_PAGE_SIZE_SUPPORTED := 16384`.
- 디바이스 필수 여부: 조사한 source.android.com 문서상 **선택사항**(developer option 형태). 디바이스 출시 필수 요구(VSR/CDD)로 전환됐는지는 **(미확인)**.
- Android 16: 16 KB 시스템에서 TLS 메모리 약 8 KB 절감 최적화 [1차: Android 16 release notes].
- Android 17: 모든 앱에 대해 16 KB backcompat 모드를 강제로 끌 수 있는 옵션 [2차].
- 앱 측: 2025-11-01부터 Google Play는 Android 15+ 타겟 신규 앱/업데이트에 16 KB 호환 요구 [2차, Developers 가이드 페이지 존재].
- BSP 영향: vendor prebuilt(.so), 펌웨어 로더, `mmap` 정렬 가정, GPU/카메라 드라이버의 `PAGE_SIZE` 하드코딩 점검 필요 (분석).

### 2.6 커널 관련 기타 변경
- ION: "no longer supported on any Android version, because all kernels supporting ION reached end of life in December 2025" → DMA-BUF heaps로 이전 필수 [1차: Android 17 release notes].
- Hardware-wrapped keys (Android 17, 신규 launch 디바이스만): 새 커널 ioctl로 key 생성/import, KeyMint 관여 제거, fstab 옵션 `wrappedkey_v0` → `wrappedkey` [1차].
- Android 16 QPR2: GPU 드라이버 syscall(IOCTL) 필터링용 SELinux 매크로 도입 [1차].
- GBL(Generic Bootloader): Android 16에서 표준화된 업데이트 가능한 bootloader 도입 [1차]. 필수 여부 **(미확인)**.

---

## 3. Treble / 벤더 호환성

### 3.1 GRF (Google Requirements Freeze) / Vendor freeze
- GRF(2020 도입): 버전 N으로 빌드된 vendor 구현은 N+3까지 인증 가능, VSR-N(해당 버전의 Vendor Software Requirements)과 vendor-side 테스트만 통과하면 됨 [2차: Esper, Android Authority. VSR/GRF 세부 문서는 파트너 전용이라 1차 공개 원문 미확인].
- Longevity GRF (2024-10 발표): vendor 소프트웨어를 7개 Android 버전까지 재사용, Snapdragon 8 Elite 최초 적용, 3년 후 major 커널 업그레이드 조건 [2차].
- AOSP 공개 문서의 vendor freeze 메커니즘 [1차: api-flags]:
  - `ro.board.api_level`: 칩셋 소프트웨어가 지원하는 vendor API level
  - `ro.board.api_frozen`: vendor freeze 확정 여부
  - `ro.vendor.api_level` = vendor freeze 시 `min(ro.board.api_level, AVendorSupport_getVendorApiLevelOf(ro.product.first_api_level))`, 아니면 `AVendorSupport_getVendorApiLevelOf(ro.product.first_api_level)`
  - `ro.llndk.api_level`: system 파티션의 LLNDK vendor API level. 이 값 이하 vendor 이미지는 해당 system 이미지와 호환.
  - "A vendor freeze is available only if you're creating an Android-compatible device."

### 3.2 Vendor API level (YYYYMM) [1차]
- Android 14-QPR3부터 SDK 정수 대신 YYYYMM 형식 도입.
- 예: SDK 35 → vendor API `202404`. 문서상 `202504`, `202604` 값 존재.
- 매핑(추정): Android 16 → 202504, Android 17 → 202604 — FCM 레벨과 동일 체계로 추정 **(미확인: Android 17 = 202604 직접 확인은 compatibility_matrix.202604.xml 존재까지만)**.

### 3.3 VNDK 폐지 [1차]
- Android 15부터 VNDK deprecated. 과거 VNDK 라이브러리는 일반 vendor/product 라이브러리처럼 해당 파티션에 설치.
- 제거: Android 15+용 VNDK APEX, `ro.vndk.version`/`ro.product.vndk.version`, vendor snapshot.
- Android 14 이하 VNDK APEX는 기존 vendor 이미지 호환을 위해 유지.
- LL-NDK는 유지(안정 API). Android 16에서 AVF 관련 LL-NDK vendor 지원 추가 [1차].
- Android 15에서 vendor overlay, NNAPI NDK API도 deprecated [1차].

### 3.4 FCM (Framework Compatibility Matrix) 레벨 [1차: FCM lifecycle]

| FCM 레벨 | 플랫폼 |
|---|---|
| 7 | Android 13 (T) |
| 8 | Android 14 (U) |
| 202404 | Android 15 (V) |
| 202504 | Android 16 (B) |
| 202604 | Android 17 — `android-17.0.0_r1` 태그에 202604 와 다음 개발 레벨 202704 존재, 레벨 5·6 제거 [1차: 릴리스 태그 소스 트리]. FCM 문서 표 반영은 **(미확인)** |

규칙 [1차]:
- 다음 프레임워크 릴리스에서 FCM 버전 지원이 빠지면: (1) 해당 matrix 파일과 관련 코드 제거, (2) max-level ≤ 해당 버전인 framework HAL을 framework manifest에서 제거.
- Trunk stable에서는 trunk_staging에서 먼저 제거하고 release 브랜치에서는 QPR 수신 디바이스를 위해 유지할 수 있음(staggered deprecation).
- 파트너가 확장한 vendor 인터페이스도 동일 방식으로 HIDL HAL deprecate/remove 권고.
- Android 16 이상에서 compatibility matrix의 HAL `optional` 태그 미지원 [1차 검색 스니펫, 원문 재확인 권장].
- ~~어떤 FCM 레벨이 Android 17에서 삭제되었는지 (미확인)~~ → **확인(2026-09-14, 1차: 릴리스 태그 소스 트리)**: `platform/hardware/interfaces` 태그별 `compatibility_matrix.<level>.xml` 목록
  - android-15.0.0_r1: 5, 6, 7, 8, 202404, 202504
  - android-16.0.0_r1: 5, 6, 7, 8, 202404, 202504, 202604
  - android-17.0.0_r1: **7**, 8, 202404, 202504, 202604, 202704 → 레벨 5(Android 11)·6(Android 12) 매트릭스 제거. 202604 = Android 17 레벨 확인.
  - `main` 브랜치의 202604 는 202504 복사본(레벨 속성만 다름)이므로 비교에는 태그 파일을 사용해야 한다.
  - 16 → 17 매트릭스 diff 결과는 [design/05 §0.1](../design/05-implementation-plan.md) 참조.

### 3.5 HIDL → AIDL
- HIDL은 Android 13 기준 deprecated, 신규 HAL은 AIDL 사용 [1차: HAL overview 검색 스니펫]. (다른 페이지는 "Android 10 이후 AIDL로 대체"로 표현 — 표현 차이 존재)
- 버전별 개별 HAL의 HIDL 제거 목록(audio/camera/composer 등)은 공개 문서에서 요약 목록을 찾지 못함 → **(미확인)**. `compatibility_matrix.<level>.xml`을 버전 간 diff해서 확정해야 함.

### 3.6 릴리스별 주요 HAL/보안 요구 (확인된 것만)

| 릴리스 | 항목 | 신뢰도 |
|---|---|---|
| Android 16 | KeyMint 4.0 — attestation에 `moduleHash`(APEX 무결성) 필드 추가 | [1차] |
| Android 16 | Configurable Audio Policy(CAP) AIDL HAL 지원 복원 (14–15에서 미지원) | [1차] |
| Android 16 | AVF/pKVM: early boot VM, Microdroid 16K pVM, Trusty TA in pVM, vendor-private SMC, device assignment | [1차] |
| Android 16 QPR2 | GPU IOCTL 필터링 SELinux 매크로 | [1차] |
| Android 17 | SCO 라우팅 책임이 Bluetooth framework → audio framework SCO management로 이동 | [1차] |
| Android 17 | Policy compatibility 조건 해당 launch 디바이스는 `memfd_class` policy capability 활성화 + `memfd_file` 클래스 대응 sepolicy 수정 | [1차] |
| Android 17 | Hardware-wrapped keys 신규 방식 (launch 디바이스) | [1차] |
| Android 17 | ION 완전 미지원 | [1차] |

---

## 4. 인증 / 테스트

### 4.1 CTS 최신 리비전 (2026-09 조회 기준) [1차: CTS downloads]

| 플랫폼 | CTS / CTS Verifier | 소스 태그 |
|---|---|---|
| Android 17 | 17 R2 | `android-cts-17.0_r2` |
| Android 16 QPR2 | 16.1 R4 | `android-cts-16.1_r4` |
| Android 16 | 16 R6 | `android-cts-16.0_r6` |
| Android 15 | 15 R9 | `android-cts-15.0_r9` |
| Android 14 | 14 R13 | `android-cts-14.0_r13` |

- Minor SDK 릴리스는 별도 CTS 버전(예: 16.1)을 가짐 [1차].
- VTS: AOSP 소스로 빌드. 공개 다운로드 리비전 정보 미확인 **(미확인)**.
- GTS, BTS(Build Test Suite), GMS 요구사항, Mainline 모듈 최소 버전(MTS/train)은 파트너 전용 문서로 공개 1차 확인 불가 **(미확인)**.
- CDD: Android 16 CDD 페이지 존재 확인 (`/docs/compatibility/16/android-16-cdd`) [1차]. Android 17 CDD 공개 여부 및 변경점 **(미확인)**.
- VTS는 GRF 규칙에 따라 vendor 이미지 기준 버전(VSR-N) carve-out 적용 [2차].

### 4.2 Mainline (APEX/APK) [1차: modular-system]
- 약 24개 모듈, APEX 또는 APK, Google Play system update 또는 파트너 OTA로 배포, 원자적 설치.
- 모듈 업데이트는 새 API를 도입하지 않음(CTS 보장 SDK/System API만 사용).
- Android 11 이하 지원은 2025 Q4 종료.
- 모듈별 필수 여부/최소 버전: 공개 문서에 명시 없음 **(미확인, GMS 요구사항 문서 필요)**.

---

## 5. 앱/동작 변경 (디바이스 제조사 관점 요약)

| 릴리스 | 변경 | 제조사 영향 | 신뢰도 |
|---|---|---|---|
| Android 16 (targetSdk 36) | edge-to-edge opt-out 불가 | 시스템 UI/내비바/cutout 대응, preload 앱 검증 | [1차] |
| Android 16 | smallest width ≥ 600dp에서 orientation/aspect ratio 제한 무시 | 태블릿/폴더블 preload 앱 레이아웃 검증 | [1차] |
| Android 16 | 앱 설치 시 dexopt를 앞단으로 이동, freeze 수 초 → 수십 ms | 성능 회귀 테스트 | [1차] |
| Android 16 QPR2 | Generational CMC GC, Linux Terminal GUI 앱 | ART/AVF 메모리 튜닝 | [1차] |
| Android 17 (targetSdk 37) | 대화면에서 orientation/resizability/aspect ratio 제약 opt-out 불가, 설정 변경 시 activity 기본 재시작 안 함 | 대화면 preload 앱 필수 대응 | [1차] |
| Android 17 | Local network access 제한, SMS OTP 보호, 시스템 contact picker, 백그라운드 오디오 hardening, strict app memory limits, generational GC, lock-free MessageQueue | preload/privileged 앱, 오디오 HAL 동작 검증 | [1차: 블로그·Developers] |
| Android 17 | 신규 API는 Jetpack Compose 전용, View는 maintenance | 시스템 앱 개발 방향 | [1차] |
| Play 정책 | 2026-08-31부터 신규 앱/업데이트 API 36+, 기존 앱 API 35+ (Wear/AAOS 35, TV/XR 34), 2026-11-01까지 연장 신청 가능 | 파트너 앱 스토어 배포 | [1차: Play Console Help / Developers] |

---

## 6. BSP 업그레이드 작업 체크리스트 및 리스크

### 6.1 사전 계획
- [ ] 목표 릴리스 결정: AOSP 공개가 Q2/Q4뿐이므로 `android-17.0.0_rX`(26Q2) 또는 26Q4 기준선 선택. Q3 QPR1 소스는 파트너 채널 필요.
- [ ] 디바이스 분류: launch vs upgrade. `ro.product.first_api_level`, `ro.board.api_level`, `ro.board.api_frozen` 값 확인.
- [ ] GRF/vendor freeze 적용 여부 결정 (vendor 이미지 유지 → system-only 업그레이드 가능성). VSR 버전 확인 (파트너 문서).
- [ ] 커널 매트릭스 확인: android12/13-5.10 사용 디바이스는 Android 17 QPR1+ 업그레이드 불가 → 커널 uprev 필수.
- [ ] 커널 EOL 확인: 5.10 계열 2027-07-01 EOL, android15-6.6 2028-07-01 EOL.

### 6.2 커널
- [ ] 목표 ACK 브랜치로 uprev (예: 6.6 → 6.12 → 6.18), vendor 모듈을 GKI KMI symbol list 기준 재빌드.
- [ ] Vendor symbol list(`abi_gki_aarch64_<vendor>`) 갱신 및 ABI 검사.
- [ ] ION 사용 코드 제거 → DMA-BUF heaps.
- [ ] 16 KB 지원 여부 결정, 모듈/펌웨어/유저공간 prebuilt `PAGE_SIZE` 가정 제거.
- [ ] Hardware-wrapped keys ioctl (Android 17 launch 디바이스), fstab `wrappedkey`.
- [ ] 월별 GKI 인증 빌드(`android17-6.18-YYYY-MM_rN`) 추적, respin 기간(6개월) 관리.

### 6.3 HAL / Treble
- [ ] 대상 FCM 레벨(202504/202604) matrix와 device manifest diff, deprecated HIDL HAL을 AIDL로 이전.
- [ ] compatibility matrix에서 `optional` 태그 제거 영향 확인 (Android 16+).
- [ ] VNDK 의존 제거 (Android 15+): `BOARD_VNDK_VERSION` 관련 설정, vendor snapshot 사용 중단.
- [ ] KeyMint 4.0 (`moduleHash`), Audio CAP AIDL, SCO audio 라우팅 변경(17) 반영.
- [ ] `check_vintf`, VTS VINTF 테스트 통과.

### 6.4 SELinux
- [ ] 신규 플랫폼 public/private sepolicy 머지, `plat_sepolicy` 호환 mapping 파일(버전 YYYYMM) 확인.
- [ ] Android 17: `memfd_class` policy capability, `memfd_file` 규칙.
- [ ] GPU IOCTL 필터링 매크로 적용 (16 QPR2+).
- [ ] neverallow 위반, `treble_sepolicy_tests` 확인.

### 6.5 부트 / 파티션 / AVB
- [ ] Android 13+ launch: generic ramdisk는 `init_boot`, `boot`는 GKI 커널만 [1차]. Android 12에서 업그레이드한 디바이스는 기존 구조 유지 가능 [1차].
- [ ] `vendor_boot`: vendor ramdisk, 커널 모듈, (recovery 파티션 없을 시) recovery 리소스 — `BOARD_MOVE_RECOVERY_RESOURCES_TO_VENDOR_BOOT := true` [1차].
- [ ] A/B recovery 사용 시 `BOARD_EXCLUDE_KERNEL_FROM_RECOVERY_IMAGE := true`, 공통으로 `BOARD_USES_GENERIC_KERNEL_IMAGE := true` [1차].
- [ ] Boot image header 버전: GKI + init_boot 구성은 v4 사용이 일반적 [사전지식]. 버전별 필수 여부 원문 **(미확인)**.
- [ ] AVB: GKI boot 이미지 서명(Google 서명 GKI 사용 시 vbmeta chain 구성), rollback index, `vbmeta_system` [사전지식] — 릴리스별 변경점 **(미확인)**.
- [ ] GBL(Android 16 도입) 채택 여부 검토 **(필수 여부 미확인)**.
- [ ] Virtual A/B: Android 13 launch 디바이스 필수 [2차: XDA]. 이후 버전 압축 방식 요구 **(미확인)**.

### 6.6 빌드 시스템
- [ ] Android 17: AOSP 소스 트리 read-only — 빌드 중 소스 트리에 쓰는 vendor 스크립트/Makefile 수정 [1차].
- [ ] trunk-stable release config(`TARGET_RELEASE`, aconfig flags) 대응 [사전지식].
- [ ] `android-latest-release` manifest 사용.

### 6.7 테스트 / 인증
- [ ] CTS/CTS Verifier 최신 리비전(17 R2 등), VTS, GTS/BTS(파트너) 실행.
- [ ] Minor SDK(36.1/37.x) 대응 시 해당 CTS 버전(16.1 등) 사용.
- [ ] Mainline 모듈 train 최신화 (GMS 요구사항 확인).
- [ ] preload 앱: edge-to-edge, 대화면 resizability, targetSdk 36/37 behavior 회귀 테스트.

### 6.8 주요 리스크

| 리스크 | 설명 | 완화 |
|---|---|---|
| 커널 EOL/매트릭스 | 5.10 커널은 Android 17 QPR1+ 미지원, 2027-07 EOL | 조기 커널 uprev 계획 |
| 4년 지원 단축 | android15-6.6 이후 ACK 4년 지원 | 제품 수명과 커널 EOL 정렬 |
| 소스 공개 지연 | AOSP Q2/Q4만 공개 | 파트너 채널 확보, 일정 버퍼 |
| HIDL 제거 | FCM 레벨 제거 시 HIDL HAL 로딩 불가 | 버전 간 matrix diff 조기 수행 |
| ION 제거 | 레거시 메모리 드라이버 | DMA-BUF heap 이전 |
| 16 KB | prebuilt 라이브러리 비호환 | ELF 정렬 점검 도구로 전수 검사 |
| sepolicy | memfd, GPU IOCTL 제한 | 조기 enforcing 테스트 |
| read-only 소스 트리 | vendor 빌드 스크립트 실패 | 출력 경로 분리 |

---

## 7. 미확인 / 추가 조사 필요 항목
1. Android 17 QPR1 정식 출시일 및 CTS 17.1 (2026-09-14 기준 미출시 보도) **(미확인)**
2. Android 16 QPR1 AOSP 소스 공개 여부 **(미확인)**
3. VSR(Vendor Software Requirements) 버전별 원문, GRF N+3 규칙의 최신 공식 표현 — 파트너 전용 **(미확인)**
4. Android 16/17 launch 디바이스 허용 커널 목록 원문 **(미확인)**
5. 16 KB 페이지의 디바이스 필수화 여부 **(미확인)**
6. ~~Android 17 FCM 레벨(202604) 및 제거된 FCM 레벨~~ → 릴리스 태그 소스 트리로 확인(§3.4). FCM 문서 표 반영은 여전히 미확인
7. 릴리스별 HIDL HAL 제거 목록 **(미확인 — matrix XML diff 필요)**
8. Android 17 CDD 공개 및 변경점, GTS/BTS/Mainline 최소 버전 **(미확인)**
9. Boot image header 버전 및 AVB 요구의 릴리스별 변경 **(미확인)**

---

## 출처

### 1차 출처 (Google 공식)
- Android 17 release notes: https://source.android.com/docs/whatsnew/android-17-release
- Android 16 release notes: https://source.android.com/docs/whatsnew/android-16-release
- Android 15 release notes: https://source.android.com/docs/whatsnew/android-15-release
- Codenames, tags, build numbers: https://source.android.com/docs/setup/reference/build-numbers
- Android common kernels: https://source.android.com/docs/core/architecture/kernel/android-common
- GKI release builds: https://source.android.com/docs/core/architecture/kernel/gki-release-builds
- android17-6.18 release builds: https://source.android.com/docs/core/architecture/kernel/gki-android17-6_18-release-builds
- android17-6.18 branch: https://android.googlesource.com/kernel/common/+/refs/heads/android17-6.18
- 16 KB page size: https://source.android.com/docs/core/architecture/16kb-page-size/16kb
- Vendor API level: https://source.android.com/docs/core/architecture/api-flags
- VNDK overview: https://source.android.com/docs/core/architecture/vndk
- FCM lifecycle: https://source.android.com/docs/core/architecture/vintf/fcm
- Compatibility matrixes: https://source.android.com/docs/core/architecture/vintf/comp-matrices
- Compatibility matrices source: https://android.googlesource.com/platform/hardware/interfaces/+/refs/heads/master/compatibility_matrices/
- HAL overview: https://source.android.com/docs/core/architecture/hal
- AIDL for HALs: https://source.android.com/docs/core/architecture/aidl/aidl-hals
- Generic boot partition: https://source.android.com/docs/core/architecture/bootloader/partitions/generic-boot
- Mainline (modular system): https://source.android.com/docs/core/ota/modular-system
- CTS downloads: https://source.android.com/docs/compatibility/cts/downloads
- Android 16 CDD: https://source.android.com/docs/compatibility/16/android-16-cdd
- Android 17 security release notes: https://source.android.com/docs/security/bulletin/android-17
- Android 17 (developers): https://developer.android.com/about/versions/17
- Android 17 is here (blog, 2026-06): https://android-developers.googleblog.com/2026/06/Android-17.html
- The First Beta of Android 17: https://android-developers.googleblog.com/2026/02/the-first-beta-of-android-17.html
- Android 16 is here (blog, 2025-06): https://android-developers.googleblog.com/2025/06/android-16-is-here.html
- Android 16 QPR2 is released (blog, 2025-12): https://android-developers.googleblog.com/2025/12/android-16-qpr2-is-released.html
- Support 16 KB page sizes: https://developer.android.com/guide/practices/page-sizes
- Play target API level: https://developer.android.com/google/play/requirements/target-sdk
- Play Console Help, target API: https://support.google.com/googleplay/android-developer/answer/11926878

### 2차 출처 (언론/커뮤니티)
- Android Authority, AOSP 연 2회 공개: https://www.androidauthority.com/aosp-source-code-schedule-3630018/
- Droid-Life, AOSP 변경: https://www.droid-life.com/2026/01/06/google-switches-to-publishing-android-source-code-twice-per-year/
- PiunikaWeb, 월별 보안 패치 유지: https://piunikaweb.com/2026/01/07/android-aosp-source-code-q2-and-q4-pixel-monthly-security-patches-unchanged/
- TechRadar: https://www.techradar.com/pro/google-set-to-reduce-the-android-source-code-releases-to-just-twice-a-year
- Esper, GRF 설명: https://www.esper.io/blog/android-dessert-bites-11-grf-323579
- Android Authority, Longevity GRF: https://www.androidauthority.com/android-longevity-grf-3493006/
- Droid-Life, Android 17 QPR1 Beta 9: https://www.droid-life.com/2026/08/17/android-17-qpr1-beta-9-update-released-for-pixel-phones/
- 9to5Google, Pixel 11 9월 업데이트(QPR1 아님): https://9to5google.com/2026/09/09/pixel-11-september-update-early/
- Android Authority, 16KB와 Android 17: https://www.androidauthority.com/android-page-sizes-explained-3644598/
- Wikipedia, Android 17 (코드네임): https://en.wikipedia.org/wiki/Android_17
- XDA, Virtual A/B 필수화: https://www.xda-developers.com/google-mandate-virtual-a-b-system-updates-android-13/
