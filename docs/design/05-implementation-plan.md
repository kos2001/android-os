# 05. 구현 계획

## 0. 이번 사전 작업에서 완료된 것

| 항목 | 위치 | 검증 |
|---|---|---|
| 도메인 조사 2건(출처·신뢰도 표기) | `docs/research/` | 1차 출처 URL 포함, 미확인 항목 명시 |
| 요구사항·아키텍처·데이터 모델·API 계약 | `docs/design/01~04`, `schema.sql` | 리뷰 필요 |
| 지식베이스 v2026-09-14 | `upgrade_core/data/releases.json` | 일관성 테스트(커널 목록·QPR 제외 규칙) |
| OTA zip 파서/검증 | `upgrade_core/ota_package.py` | 합성 zip으로 offset·STORED·거부 사유 테스트 |
| update-check 매칭 | `upgrade_core/matcher.py` | incremental 우선·full 폴백·다운그레이드 차단·필터 테스트 |
| 버킷팅·에러코드·부팅판정·halt | `upgrade_core/rollout.py` | 비율 증가 시 대상 유지, `error_code.h` 플래그 분해 테스트 |
| Readiness 규칙 7종 | `upgrade_core/readiness.py` | 커널 호환/QPR/EOL, ION, VNDK, memfd, HIDL, 16KB 테스트 |

`python3 -m unittest discover -s tests -t .` → 30 tests OK (2026-09-14).

## 0.1 진행 결과 (2026-09-14, 2차)

### P0 — 실패키지 검증 (부분 완료)

사내 샘플 패키지·실기기가 없어 **Google 공개 Pixel OTA** 로 대체 검증했다. zip 전체를 받지 않고 HTTP Range 로 중앙 디렉터리·metadata·payload 헤더만 읽었다(`upgrade_core/remote.py`).

| 패키지 | 크기 | 결과 | Range 요청 / 전송량 |
|---|---|---|---|
| `lynx-ota-cp2a.260705.006` (Android 17, SPL 2026-07-05) | 3.16 GB | ready, payload offset 4534 — metadata 선언값과 전 엔트리 일치, `CrAU` 확인 | 4회 / 156 KB |
| `lynx-ota-bp4a.260205.001` (Android 16, SPL 2026-02-05) | 2.88 GB | ready, 동일 | 6회 / 327 KB |
| `stallion-ota-cp2a.260805.005` (Android 17, SPL 2026-08-05) — API 경유 | 3.57 GB | ready | 3회 / 385 KB |

실파일로 새로 확인해 코어에 반영한 사실:
- `METADATA_HASH` = payload.bin 앞 `METADATA_SIZE` 바이트의 SHA-256(base64) → 등록 시 검증 추가 (기기 오류 26 사전 차단)
- property-files 의 `metadata`, `metadata.pb` 이름은 `META-INF/com/android/metadata[.pb]` 엔트리를 가리킴 → 별칭 처리
- 공개 Pixel 패키지는 `ota-streaming-property-files` 에 `metadata`, `metadata.pb` 까지 포함, `otacert` 만 압축 엔트리

**남은 P0 항목**: ① incremental 패키지 실검증(Google 은 공개하지 않음 → 사내 패키지 필요) ② 실기기 `update_engine_client` 스트리밍 설치.

### P1 — Readiness MVP (완료)

| 항목 | 위치 |
|---|---|
| VINTF manifest(+fragments)·framework matrix 파서, matrix diff, manifest×matrix 검사 (libvintf `supportedBy` 규칙) | `upgrade_core/vintf.py` |
| 규칙 추가: `FCM_LEVEL_REMOVED`(blocker), `HAL_NOT_IN_MATRIX`/`HAL_VERSION_UNSUPPORTED`(warning), `HAL_INSTANCE_NOT_ALLOWED`(info) | `upgrade_core/readiness.py` |
| KB: 릴리스 태그별 matrix 레벨 목록(1차: 소스 트리) — **Android 17 에서 레벨 5·6 제거, 최소 7** | `releases.json` `fcm_matrices_in_tree` |
| FastAPI + SQLite, API 키 RBAC, 감사 로그, 작업 항목 자동 생성(blocker/warning) | `backend/app.py`, `backend/store.py` |
| AOSP 태그 matrix 가져오기 | `scripts/import_matrices.py` |
| 테스트 48개(네트워크 1개 선택 실행), 실서버 스모크: 17 태그 matrix 6개 import → readiness run → Pixel OTA inspect | `tests/` |

실제 AOSP 데이터에서 얻은 사실(릴리스 태그 matrix diff):
- 202504(16) → 202604(17): `health.storage`(aidl) 제거, `bluetooth.gatt`·`motioncontext`·`npu`·`security.see.devicestate`·`security.timestamp` 추가, 34개 HAL 버전 범위 상향
- level 8 → 202604: HIDL `audio`, `audio.effect`, `bluetooth`, `graphics.mapper`, `media.c2`, `media.omx`, `renderscript`, `soundtrigger`, `tetheroffload.*` 없음
- 주의: `main` 브랜치의 202604 파일은 202504 복사본(레벨 번호만 다름) → 반드시 릴리스 태그 사용

## 0.2 진행 결과 (2026-09-14, 3차) — P2·P3·P4 MVP

| 단계 | 구현 | 검증 |
|---|---|---|
| P2 패키지 등록 | `POST /admin/v1/packages {url, sha256?}` → HTTP Range 검사 → build 자동 등록(post-build/timestamp/SPL) → `ready`/`rejected`(사유 저장). 호스트 allowlist, payload 필드 불변 트리거, retire | 합성 zip 테스트 + **실 Pixel OTA 등록**(lynx CP2A.260705.006) |
| P3 기기 API | `POST /device/v1/update-check` — 체크인 기록 → 부팅 판정(fingerprint 비교) → 롤아웃 매칭 → assignment upsert → `applyPayload` 인자 응답. `POST /device/v1/events` — 멱등 키, native ErrorCode 분해, 상태 전이(취소 48 → offered, 실패 → failed). 기기 공유 키 인증 | 설치 성공·부팅 폴백 재제공·중복 이벤트·타 기기 assignment 차단 테스트, 실서버에서 Android 16 기기 요청 → 17 full 패키지 응답 |
| P4 롤아웃 | 상태 머신(start/promote/pause/resume/halt/complete), 단계별 soak 시간 강제, 안정적 해시 버킷, 지표(에러 코드 분포), `evaluate-halt`(dry-run/apply), 백그라운드 자동 halt 루프, `stop_new`/`stop_all_pending`, delta 후보 리포트, 감사 로그 | 단계 승격·버킷 유지·halt 후 기존/신규 기기 분기·백그라운드 halt 테스트 |
| P0 잔여 지원 | `scripts/device_ota_test.py` — adb 로 기기 속성 수집 → update-check → `update_engine_client --update --follow --payload --offset --size --headers`(AOSP 소스로 플래그 확인) → 이벤트 보고 → 재부팅 후 체크인 | 요청 조립·원격 쉘 quoting 단위 테스트. **실기기 실행은 미수행** |

### 코드 리뷰 반영 (독립 리뷰 12건 — 9건 재현, 3건 코드 분석)

| # | 결함 | 조치 | 회귀 테스트 |
|---|---|---|---|
| 1 | 재부팅 전 체크인을 부팅 폴백으로 오판 → 재설치 루프 | `boot_id` 비교로만 폴백 판정, `PENDING_REBOOT`, `max_attempts` | `test_update_check_install_and_boot_outcomes`, `test_1_retry_limit` |
| 2 | 재시도 시 실패·폴백이 지표에서 사라져 자동 halt 무력화 | assignment `attempt` + 이벤트 이력 기반 집계 | `test_2_failures_survive_retry_in_metrics` |
| 3 | SSRF(리다이렉트 추종, 기본 전체 호스트 허용, 오류 메시지 오라클) | 리다이렉트 거부, allowlist 필수, 공인 IP 검사, 네트워크 오류 메시지 일반화 | `test_3_*` |
| 4 | 메모리 무제한(Range 무시 응답, zip bomb, 거대 METADATA_SIZE, 캐시) | 206+Content-Range 검증·요청 크기만 읽기, 중앙 디렉터리/텍스트 엔트리/메타데이터 상한, LRU 캐시 | `test_4_*` |
| 5 | promote 와 halt 경합 시 halt 가 풀림 | 읽기·쓰기 단일 트랜잭션 + `WHERE state = ?` 조건부 갱신 | `test_5_*` |
| 6 | assignment 없는 이벤트 중복 제거 안 됨(NULL) | `COALESCE` 표현식 유니크 인덱스 | `test_6_*` |
| 7 | 이벤트 배치 부분 커밋 | 전체 검증 후 단일 트랜잭션 | `test_7_*` |
| 8 | 손상 zip 이 500 | 손상 관련 예외 → `OtaPackageError`(422) | `test_8_*` |
| 9 | 비숫자 에러코드 규칙이 halt 평가를 영구 실패시킴 | 스키마 검증(422) | `test_9_*` |
| 10 | 여러 롤아웃·일시정지 시 진행 중 설치 무시 | 진행 중 할당 우선, paused 에서도 계속 제공 | `test_10_*` |
| 11 | 이전 시도의 늦은 이벤트가 최신 시도 상태를 덮어씀 | attempt 불일치 이벤트는 상태 미반영 | `test_11_*` |
| 12 | 인증 fail-open(빈 키, 미설정 시 무인증) | 빈 키 거부, 상수시간 비교, 명시적 개발 모드 외 시작 거부 | `test_fails_closed_without_configuration` |

남은 알려진 한계: 공유 기기 키 보유자는 임의 `device_hash` 로 가짜 이벤트를 보내 halt 를 유발할 수 있음 → Q6(기기별 인증) 확정 필요. DNS rebinding(검사 후 재해석)은 오리진 allowlist 로 완화.

`.venv/bin/python -m unittest discover -s tests -t .` → **73 tests OK** (네트워크 1 skip). 운영 모드 실서버 스모크: 무인증 401, 역할 403, 실 Pixel OTA 등록 ready, 설정 누락 시 시작 거부.

제약·후속 과제:
- 인증은 API 키/공유 기기 키 — Q6(기기 인증) 확정 후 mTLS 또는 Key Attestation 기반으로 교체
- SQLite 단일 커넥션 — P5 에서 PostgreSQL(`schema.sql`)·이벤트 파티션으로 이전
- sha256 은 파이프라인 제공값을 저장만 함(원격 전체 해시 미계산). 무결성은 `FILE_HASH`/`METADATA_HASH`(update_engine 검증)에 의존
- 다운그레이드 패키지 승인 워크플로(OT-13 예외) 미구현 — 현재는 항상 rejected
- `SWITCH_SLOT_ON_REBOOT`, `POWERWASH` 헤더 값 형식은 원문 미확인이라 응답에 넣지 않고 `policy.switch_slot_on_reboot`, `package.wipe` 로만 전달

## 0.3 진행 결과 (2026-09-19) — 커널 준비도 (research/01 §6.2)

| 항목 | 구현 | 검증 |
|---|---|---|
| GKI 릴리스 문자열 | `uname -r` → 버전·브랜치·KMI generation (`<w>.<x>.<y>-<androidNN>-<k>[-…]`, 비 GKI 거부) | 단위 테스트 |
| kernel .config | 텍스트·`config.gz` 파싱 → `CONFIG_ION`·페이지 크기·DMA-BUF heaps·MODVERSIONS 힌트, 프로파일 반영 | 단위·API 테스트 |
| vendor 모듈(.ko) | ELF64 LE ET_REL 파서(표준 라이브러리) → `.modinfo`(name/vermagic/license/depends), import 심볼, `__ksymtab_*` export | 합성 ELF 테스트(손상·ELF32·BE·ET_EXEC 거부) |
| KMI 검사 | 모듈 import − (목표 브랜치 symbol list ∪ vendor 모듈 export) → `KMI_SYMBOL_MISSING`(warning, 20개까지 개별 + 나머지 요약), vermagic 브랜치 불일치 → `KERNEL_MODULE_REBUILD`(info) | 단위·API 테스트 |
| uprev 후보 | 목표 릴리스 지원 브랜치 중 현재 이상, EOL·QPR 제외·지원 기간 기준 권장(없으면 EOL 최장). `KERNEL_COMPAT`/`_QPR`/`EOL` finding 에 권장 브랜치 표기, `target_kernel_branch` 로 uprev 후 기준 판정 | 단위·API 테스트 |
| symbol list 가져오기 | `scripts/import_symbol_lists.py --branch …` — gitiles `gki/aarch64/symbols/`(android16-6.12+) 또는 `android/abi_gki_aarch64*`(이전), 429 재시도 | **실데이터**: android14-6.1 36파일 8,932개, android16-6.12 42파일 10,542개, android17-6.18 25파일 9,548개 등록 |
| 웹 콘솔 | 플랫폼 상세 “커널” 카드(uname·config·.ko 업로드, uprev 후보), 판정 기준 커널 선택 | 브라우저 확인 |

실데이터에서 확인한 사실: android16-6.12 의 `meizu` symbol list 는 비어 있음 → 빈 파일 허용. android16-6.12 에서 `kmalloc_trace` 는 KMI 에 없음(6.12 에서 `_noprof` 계열로 변경).

한계: GKI 모듈(system_dlkm) export 는 `abi_gki_protected_exports_aarch64` 가 있는 브랜치(android14-6.1)만 반영 → 다른 브랜치에서는 누락으로 보일 수 있어 warning 으로만 보고. CRC(modversions) 일치·실제 모듈 로드는 검사하지 않음(ABI 도구·실기기 필요). 실제 vendor `.ko` 로는 미검증(합성 ELF 로만 테스트).

`.venv/bin/python -m unittest discover -s tests -t .` → **102 tests OK** (네트워크 1 skip).

## 0.4 진행 결과 (2026-09-19) — 드라이버 인벤토리

| 항목 | 구현 | 검증 |
|---|---|---|
| 모듈 메타데이터 | `.modinfo` 의 `description`, `alias`(MODULE_DEVICE_TABLE) 저장 — 이전에 저장된 모듈은 기본값 | 단위 테스트 |
| 분류 | 커널 드라이버: import 한 커널 API 접두사(drm_·v4l2_·snd_·cfg80211_·input_·regulator_ …) 점수, alias 로 버스(of·i2c·sdio·pci·usb·platform …). HAL: `android.hardware.<name>` 매핑. **추정**이므로 판정에 쓰지 않음 | 단위 테스트 |
| 판정 연결 | `ion_*` 를 import 하는 드라이버가 있으면 프로파일 `uses_ion` 과 무관하게 `ION_REMOVED` blocker, 드라이버 이름 표기 | 단위·API 테스트 |
| API·콘솔 | `GET /admin/v1/platforms/{id}/drivers` (판정 기준 커널 브랜치의 KMI 누락 수 포함), 플랫폼 상세 “드라이버 인벤토리”(서브시스템별 색상), 소개 페이지 항목 | 브라우저 확인(실제 android17-6.18 symbol list 기준) |

한계: 드라이버 분류는 import 심볼 기반 추정이라 여러 프레임워크를 쓰는 드라이버는 가장 많이 쓰는 쪽으로만 분류됨. 드라이버 ↔ HAL 의 실제 연결(어떤 HAL 이 어떤 커널 드라이버를 쓰는지)은 알 수 없어 같은 서브시스템에 나란히 보여 줄 뿐임.

## 1. 단계별 계획

선행 조건: [00 §3](00-scope-assumptions.md) 질문 Q1(범위), Q6(기기 인증), Q7(인프라) 확정.

| 단계 | 목표 | 작업 | 완료 기준 |
|---|---|---|---|
| **P0 검증** | 실 패키지로 코어 검증 | 실제 서명된 A/B OTA zip(full·incremental 각 1개)으로 `inspect_ota_package` 실행, `payload_properties.txt`·metadata 의 `ota-streaming-property-files` 와 대조. 실기기에서 반환된 url/offset/size/headers 로 `update_engine_client --payload=... --offset=... --size=... --headers=...` 설치 성공 | 실기기 1대 스트리밍 설치 성공 |
| **P1 Readiness MVP** | 엔지니어가 플랫폼별 업그레이드 blocker를 확인 | FastAPI `/admin/v1/platforms`, `readiness-runs`, `kb/releases`; SQLite; manifest XML → HAL 목록 파서; FCM matrix diff(RD-07) | 실제 플랫폼 2종 판정 결과를 BSP 담당자가 검토 |
| **P2 OTA Ingest** | 파이프라인이 패키지 등록 | `/admin/v1/builds`, `/packages`(object key 방식), 객체 저장소 어댑터(로컬/S3), ingest 워커, 불변성 트리거 | 거부 사유가 API에 노출, ready 패키지 수정 불가 |
| **P3 Update-check** | 내부 기기에 배포 | `/device/v1/update-check`, `/events`, assignment 저장, 부팅 판정, 다운로드 토큰 발급 | testing 채널 내부 기기 N대 incremental/full 설치·판정 기록 |
| **P4 Rollout 운영** | 단계 배포·자동 halt | 롤아웃 상태 머신 API, 스냅샷 집계 작업, halt 평가, 알림(Slack 등), 감사 로그, delta 후보 리포트 | 스테이징에서 인위적 오류 주입 시 자동 halt |
| **P5 운영 전환** | PostgreSQL·CDN·인증 | 이벤트 파티션·보존, mTLS/토큰 인증, RBAC, 부하 테스트(update-check p95 < 200ms) | 보안 리뷰 통과 |

## 2. 리스크와 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| 요구사항 범위 오해(가정 A1/A2) | 설계 재작업 | Q1 우선 확인. 코어는 도메인별 독립 모듈이라 한쪽만 채택 가능 |
| 파트너 전용 문서(VSR, GMS, GTS) 미확보 | readiness 규칙 누락 | KB 신뢰도 표기, 권한 확보 후 규칙 추가. unverified 사실은 blocker 판정에 쓰지 않음 |
| 레거시 텍스트 metadata 누락/형식 변화 | ingest 실패 | P0 실패 시 `metadata.pb` 파서(protobuf) 추가 — ADR D3 재검토 |
| update_engine minor version 비호환 delta | 구형 기기 설치 실패(45) | 에러 45 발생 시 해당 source에 full만 제공하도록 롤아웃 필터, P4에서 자동화 검토 |
| 폴백 판정 오탐(체크인 지연·다른 빌드) | 잘못된 halt | `boot_outcome` 판정 불가(None) 분리, 최소 표본(min_sample) |
| AOSP 소스 연 2회 공개 | 목표 기준선 일정 지연 | 26Q2/26Q4 기준선 계획, QPR은 파트너 채널 |
| 커널 5.10 기기 | Android 17 QPR1+ 불가 | readiness `KERNEL_COMPAT_QPR` 경고로 조기 가시화 |

## 3. 다음 액션 (담당 확인 필요)

1. Q1~Q9 답변 수집 → 00 문서 갱신 (미해결: 사용자 확인 필요)
2. 사내 incremental OTA zip 1개 + 실기기 1대로 P0 잔여 항목 수행
3. 대상 플랫폼 실데이터 등록: `POST /admin/v1/platforms` → `PUT …/manifest`(vendor manifest + vintf_fragments) → `POST …/readiness-runs`
4. API 계약(04) 기기 Updater 앱 담당과 리뷰
5. P2(OTA Ingest) 착수: `packages/inspect` 를 비동기 ingest 작업 + `ota_package` 저장으로 확장
