# android-os — Android OS 업그레이드 backend (사전 작업)

Android 기기/BSP의 메이저 OS 업그레이드(예: 16 → 17)를 지원하는 backend의 **조사·설계·코어 로직**.

- **Upgrade Readiness** — 플랫폼 프로파일(커널 브랜치, VNDK/ION, HAL 등)을 목표 릴리스와 비교해 blocker/warning 판정
- **OTA Delivery** — 서명된 A/B OTA 패키지 등록·update-check 매칭·단계 배포·텔레메트리·자동 halt

> 범위·가정·미결 질문은 [docs/design/00-scope-assumptions.md](docs/design/00-scope-assumptions.md) 를 먼저 볼 것.

## 문서

| 문서 | 내용 |
|---|---|
| [research/01 플랫폼 업그레이드 요구사항](docs/research/01-platform-upgrade-requirements.md) | 릴리스·API 레벨, GKI 커널 매트릭스/EOL, Treble·VNDK·FCM, CTS, BSP 체크리스트 |
| [research/02 OTA 전달 메커니즘](docs/research/02-ota-delivery-mechanics.md) | A/B·VABC, payload/metadata, UpdateEngine API, 보안·롤백, 서버 설계 시사점 |
| [design/01 요구사항](docs/design/01-requirements.md) | 기능(RD-*, OT-*)·비기능 요구사항 |
| [design/02 아키텍처](docs/design/02-architecture.md) | 컴포넌트, 시퀀스, ADR |
| [design/03 데이터 모델](docs/design/03-data-model.md) · [schema.sql](docs/design/schema.sql) | 엔터티, 불변식, DDL |
| [design/04 API 명세](docs/design/04-api-spec.md) | `/device/v1`, `/admin/v1` 계약 |
| [design/05 구현 계획](docs/design/05-implementation-plan.md) | 단계(P0~P5), 리스크 |

## 코어 (`upgrade_core`, 표준 라이브러리만 사용)

| 모듈 | 기능 |
|---|---|
| `ota_package` | OTA zip → payload offset/size, `payload_properties`, metadata(pre/post build, timestamp, SPL, 플래그), 거부 사유 |
| `matcher` | 기기 상태 × 롤아웃 → incremental 우선/full 폴백, timestamp·SPL 하락 차단 |
| `rollout` | 안정적 해시 버킷, native ErrorCode 분해, 부팅 성공/폴백 판정, halt 평가 |
| `readiness` | `data/releases.json` 기반 규칙 판정 (커널·FCM 레벨·ION·VNDK·memfd·HAL·16KB) |
| `vintf` | device manifest(+fragments)·framework matrix 파싱, matrix diff, manifest×matrix 검사 |
| `remote` | HTTP Range 원격 파일 — 수 GB OTA zip 을 수백 KB 만 읽고 검사 |
| `kernel` | GKI `uname -r`·kernel `.config`(.gz) 해석, vendor `.ko` ELF 분석, KMI symbol list 대조, 커널 uprev 후보 |

```sh
python3 -m unittest discover -s tests -t .   # 코어만 (Python ≥ 3.10)
python3 -m venv .venv && .venv/bin/pip install -r requirements-server.txt
.venv/bin/python -m unittest discover -s tests -t .                              # API 포함
ANDROID_OS_NETWORK_TESTS=1 .venv/bin/python -m unittest tests.test_remote        # 공개 Pixel OTA 실검증
```

## 웹 콘솔 (`web/`)

React + TypeScript + Tailwind 운영 콘솔. 개요 대시보드, 플랫폼 준비도 판정·작업 항목, 릴리스 지식베이스(커널 지원 기간 차트),
VINTF matrix 비교, OTA 패키지 등록·검사, 롤아웃 단계 운영(진행 추이·오류 코드·자동 중단 평가), Delta 후보, 감사 로그.
명령 팔레트(⌘K), 라이트/다크 테마, 모바일 메뉴, 모든 차트의 표 보기, **한국어·영어 UI**(상단 바 `EN/한` 버튼 또는 설정 — 첫 방문은 브라우저 언어)를 지원한다.
readiness finding 은 `title`/`detail`(한국어)과 `title_en`/`detail_en`(영어)을 함께 저장·응답한다(영어 도입 전 판정은 한국어만).

```sh
cd web && npm ci && npm run build      # web/dist 생성 → backend 가 / 에서 서빙 (index.html no-cache, 해시 에셋 immutable)
ANDROID_OS_DEV_MODE=1 .venv/bin/uvicorn --factory backend.app:create_app --port 8020   # http://127.0.0.1:8020
.venv/bin/python scripts/seed_demo.py   # (개발 모드 전용) 실제 공개 OTA·AOSP matrix + 시뮬레이션 기기 데이터

cd web && npm run dev                  # 개발 서버 http://127.0.0.1:5190 (API 는 8020 으로 프록시)
```

## Backend API (P1 Readiness)

```sh
ANDROID_OS_DEV_MODE=1 .venv/bin/uvicorn --factory backend.app:create_app --port 8020   # 문서: http://127.0.0.1:8020/docs
.venv/bin/python scripts/import_matrices.py --release 17 --tag android-17.0.0_r1   # AOSP 태그 matrix 등록

A=http://127.0.0.1:8020/admin/v1
curl -X POST $A/platforms -H 'content-type: application/json' \
  -d '{"name":"my-bsp","soc":"my-soc","android_version":"15","kernel_branch":"android14-6.1"}'
curl -X PUT  $A/platforms/1/manifest -F files=@vendor/etc/vintf/manifest.xml -F files=@fragment.xml
curl -X POST $A/platforms/1/readiness-runs -H 'content-type: application/json' -d '{"target_release":"17"}'
# 커널: symbol list 등록(AOSP) → uname·config·vendor 모듈 업로드 → uprev 후 기준 판정
.venv/bin/python scripts/import_symbol_lists.py --branch android17-6.18
curl -X PUT $A/platforms/1/kernel -F kernel_release="$(adb shell uname -r)" -F config=@config.gz \
  -F modules=@vendor_dlkm/lib/modules/foo.ko
curl "$A/platforms/1/kernel/uprev?target_release=17"
curl -X POST $A/platforms/1/readiness-runs -H 'content-type: application/json' \
  -d '{"target_release":"17","target_kernel_branch":"android17-6.18"}'
curl -X POST $A/packages/inspect -H 'content-type: application/json' -d '{"url":"https://.../ota.zip"}'
```

## Backend API (P2~P4 OTA Delivery)

```sh
# 패키지 등록 (Range 지원 https 오리진) → 롤아웃 → 기기 확인
curl -X POST $A/packages -H 'content-type: application/json' -d '{"url":"https://dl.google.com/dl/android/aosp/lynx-ota-cp2a.260705.006-f4d6d546.zip"}'
curl -X POST $A/rollouts -H 'content-type: application/json' -d '{"name":"lynx-17","target_fingerprint":"google/lynx/lynx:17/CP2A.260705.006/15641320:user/release-keys","channel":"stable","stages":[{"percent":1,"min_soak_hours":24},{"percent":100}],"halt_rules":{"min_sample":200,"max_error_rate":0.03}}'
curl -X POST $A/rollouts/1/start
curl -X POST http://127.0.0.1:8020/device/v1/update-check -H 'content-type: application/json' \
  -d '{"device":"lynx","fingerprint":"google/lynx/lynx:16/BP4A.260205.001/14624666:user/release-keys","build_timestamp":1766287731,"security_patch":"2026-02-05","channel":"stable","device_hash":"<64 hex>"}'

# 실기기 검증 (userdebug + adb root)
python3 scripts/device_ota_test.py --api http://HOST:8020 --channel testing --apply
```

| 환경변수 | 의미 |
|---|---|
| `ANDROID_OS_DB` | SQLite 경로 (기본 `android_os.db`) |
| `ANDROID_OS_DEV_MODE` | `1` 이면 인증·패키지 호스트 제한 없이 실행 (로컬 개발 전용). 아니면 아래 키·호스트 설정이 없을 때 시작 거부 |
| `ANDROID_OS_DEVICE_KEYS` | 기기 API 공유 키 목록 |
| `ANDROID_OS_AUTO_HALT_INTERVAL_S` | 자동 halt 평가 주기 (기본 300, 0 = 비활성) |
| `ANDROID_OS_API_KEYS` | `key:actor:role,...` (role: admin/engineer/release_manager/operator/pipeline/viewer) |
| `ANDROID_OS_PACKAGE_HOSTS` | `packages/inspect` 허용 호스트 목록 (SSRF 방지, 운영 필수) |

진행 현황·검증 결과: [design/05 §0.1](docs/design/05-implementation-plan.md)

```python
from datetime import date
from upgrade_core.readiness import PlatformProfile, evaluate
evaluate(PlatformProfile("my-soc", "15", "android13-5.10", uses_ion=True), "17", date.today())

from upgrade_core.ota_package import inspect_ota_package
with open("pony-ota.zip", "rb") as f:
    info = inspect_ota_package(f)
print(info.ready, info.reject_reasons, info.payload_offset, info.apply_payload_headers())
```

지식베이스(`upgrade_core/data/releases.json`)는 2026-09-14 기준이며 각 항목에 출처가 있다. 새 릴리스(예: 17-QPR1 정식, 26Q4)가 나오면 이 파일과 `tests/test_readiness.py` 를 함께 갱신한다.
