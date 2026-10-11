# 04. API 명세 (초안)

> 구현 상태(2026-09-14): 이 문서의 계약은 `backend/app.py`(Readiness), `backend/ota_api.py`(OTA) 에 구현됨. 실행 중 서버의 `/docs`(OpenAPI)가 필드 단위 정본이다. 구현과의 차이:
> - 응답 `package.headers` 에는 payload 4개 키만 포함. `AUTHORIZATION`/`USER_AGENT` 는 기기 앱이 추가 (다운로드 토큰 발급은 Q6·Q7 확정 후)
> - `target.display_version`, `android_release` 대신 `target.incremental`, `sdk_level` 반환
> - 패키지 등록은 `object_key` 대신 `url`(Range 지원 오리진) 방식
> - 롤아웃 상태 전이 경로: `/admin/v1/rollouts/{id}/{start|promote|pause|resume|halt|complete}`, 자동 halt 수동 평가 `POST …/evaluate-halt?apply=`
>
> **코드 리뷰 반영(2026-09-14)으로 추가된 계약**
> - update-check 요청 `boot_id`(`/proc/sys/kernel/random/boot_id`), 이벤트 `boot_id`(updated_need_reboot 시). 서버는 **fingerprint == source 이고 boot_id 가 설치 시점과 다를 때만** `boot_fallback` 으로 판정한다. boot_id 가 없으면 폴백은 판정하지 않는다(재부팅 전 체크인과 구별 불가).
> - 응답 `attempt`, 이벤트 `attempt`(선택). 실패·폴백 후 재제공 시 attempt 가 오르고, 이전 attempt 의 늦은 이벤트는 이력에만 저장되며 상태를 바꾸지 않는다. 지표·자동 halt 는 attempt 별 이벤트 이력으로 계산한다.
> - `reason` 추가 값: `PENDING_REBOOT`(설치 완료·재부팅 대기, 재설치 방지), `RETRY_LIMIT_REACHED`(`policy.max_attempts`, 기본 2).
> - 진행 중(offered/downloading/installed_pending_reboot) 할당이 있으면 새 롤아웃보다 우선하고, 롤아웃이 paused 여도 계속 제공한다.
> - 이벤트 배치는 전체 검증 후 한 트랜잭션으로 저장(부분 커밋 없음). `halt_rules.max_error_code_rate` 키는 숫자 문자열만 허용.
> - 운영 설정 누락 시 시작 거부(fail-closed). `ANDROID_OS_DEV_MODE=1` 에서만 무인증. 패키지 URL 은 https + 호스트 allowlist + 공인 IP + 리다이렉트 거부.

- 기기용 `/device/v1` — 기기 인증(Q6: mTLS 또는 서명 토큰), 응답은 짧고 캐시 불가.
- 운영용 `/admin/v1` — SSO + RBAC(`engineer`, `release_manager`, `operator`, `pipeline`).
- 오류 형식: `{"error": {"code": "PACKAGE_REJECTED", "message": "...", "details": {...}}}`

## 1. Device API

### 1.1 `POST /device/v1/update-check`

요청 (필드 출처는 [research/02 §5.2](../research/02-ota-delivery-mechanics.md))
```json
{
  "device": "pony",
  "fingerprint": "vendor/pony/pony:16/BP2A.250605.031/13101520:user/release-keys",
  "incremental": "13101520",
  "build_timestamp": 1749100000,
  "security_patch": "2026-06-05",
  "sdk_level": 36,
  "slot_suffix": "_a",
  "channel": "stable",
  "carrier": "KT", "region": "KR", "sku": "pony_kr",
  "device_hash": "3f2a…(64 hex, OEM 정의 salt 해시)",
  "last_update": {"assignment_id": 812, "status": 6, "error_code": 0},
  "conditions": {"free_bytes": 9876543210, "battery_pct": 72, "charging": false, "network": "unmetered"}
}
```

응답 — 업데이트 있음
```json
{
  "update_available": true,
  "assignment_id": 913,
  "rollout": {"id": 41, "name": "pony-17-stable"},
  "target": {
    "fingerprint": "vendor/pony/pony:17/CP2A.260705.012/14200001:user/release-keys",
    "android_release": "17", "sdk_level": 37, "security_patch": "2026-07-05",
    "display_version": "CP2A.260705.012"
  },
  "package": {
    "type": "incremental", "wipe": false,
    "url": "https://cdn.example.com/builds/pony/14200001/9c1e…c7.zip",
    "file_size": 1532000000, "sha256": "9c1e…c7",
    "payload_offset": 1109, "payload_size": 1531998000,
    "payload_metadata": {"offset": 1109, "size": 120345},
    "streaming_property_files": "payload.bin:1109:1531998000,payload_properties.txt:1531999200:154",
    "headers": [
      "FILE_HASH=lURPCIkIAjtMOyB/EjQcl8zDzqtD6Ta3tJef6G/+z2k=",
      "FILE_SIZE=1531998000",
      "METADATA_HASH=tBvj43QOB0Jn++JojcpVdbRLz0qdAuL+uTkSy7hokaw=",
      "METADATA_SIZE=120345",
      "AUTHORIZATION=Bearer <단기 다운로드 토큰>",
      "USER_AGENT=pony-updater/1.4"
    ]
  },
  "policy": {"require_unmetered": true, "min_battery_pct": 30, "install_window": "02:00-05:00",
             "switch_slot_on_reboot": true, "mandatory": false},
  "next_check_after_s": 21600
}
```
- `headers` 는 `UpdateEngine.applyPayload(url, payload_offset, payload_size, headers)` 에 그대로 전달한다.
- 응답 — 업데이트 없음: `{"update_available": false, "reason": "UP_TO_DATE|NOT_IN_ROLLOUT|NO_COMPATIBLE_PACKAGE|ROLLOUT_HALTED", "next_check_after_s": 21600}`
  - `reason` 은 운영 진단용. 공개 여부는 보안 검토 후 결정.
- 부수효과: `last_update` 와 현재 fingerprint로 부팅 성공/폴백 판정(OT-09), assignment 생성(OT-06, 결정적).

매칭 절차 (구현: `upgrade_core.matcher.select_update`)
1. 기기 필터(device, channel, carrier/region/sku)에 맞는 `active` 롤아웃 조회
2. `bucket(rollout_id, device_hash) < current_percent × 100` 인지 확인
3. 롤아웃 target build의 `ready` 패키지 중 `device ∈ pre_device`
4. 하위호환 검증: `post_timestamp > build_timestamp`, `post_spl ≥ security_patch` (downgrade 승인 시 예외)
5. `incremental` 이고 `fingerprint ∈ pre_builds` 인 것 우선 → 없으면 `full`

### 1.2 `POST /device/v1/events`
```json
{
  "device_hash": "3f2a…",
  "events": [
    {"assignment_id": 913, "type": "download_started", "occurred_at": "2026-09-14T02:01:00Z"},
    {"assignment_id": 913, "type": "status", "update_status": 3, "progress": 0.42, "occurred_at": "…"},
    {"assignment_id": 913, "type": "error", "error_code": 1073741833, "occurred_at": "…"},
    {"assignment_id": 913, "type": "updated_need_reboot", "occurred_at": "…"}
  ]
}
```
- 배치 최대 100건, 멱등 키 `(assignment_id, type, occurred_at)`.
- `error_code` 는 native ErrorCode 원형(플래그 비트 포함). 서버가 `base = code & 0x0FFFFFFF`, 플래그(`DevMode 1<<31`, `Resumed 1<<30`, `TestImage 1<<29`, `TestOmahaUrl 1<<28` — `error_code.h` 확인)로 분해 저장. `base ≥ 2000` 은 `kOmahaRequestHTTPResponseBase + HTTP 상태코드`. 위 예시 `1073741833` = `Resumed | 9(DownloadTransferError)`.
- 응답 `202 {"accepted": 4}`

## 2. Admin API

| 메서드 | 경로 | 역할 | 설명 |
|---|---|---|---|
| GET | `/admin/v1/kb/releases` | 전체 | 지식베이스(버전·커널·FCM, 출처·신뢰도) |
| POST | `/admin/v1/platforms` | engineer | 플랫폼 프로파일 등록 |
| PUT | `/admin/v1/platforms/{id}/hals` | engineer | HAL 목록 교체(또는 manifest XML 업로드) |
| POST | `/admin/v1/platforms/{id}/readiness-runs` | engineer | `{"target_release": "17", "target_kernel_branch"?: "android17-6.18"}` → finding 목록. `target_kernel_branch` 를 주면 그 커널로 uprev 한 뒤를 기준으로 커널 규칙·KMI 검사 (현재보다 오래된 브랜치는 422). 응답 `kmi_check` 에 KMI 검사 포함 여부 |
| PUT | `/admin/v1/platforms/{id}/kernel` | engineer | multipart `kernel_release`(uname -r, GKI 형식·플랫폼 브랜치 일치) · `config`(.config 또는 config.gz) · `modules`(.ko 여러 개). 준 항목만 교체. config 의 `CONFIG_ION` 은 `uses_ion` 에, `CONFIG_ARM64_16K_PAGES=y` 는 `supports_16kb=true` 에 반영(감사 로그) |
| GET | `/admin/v1/platforms/{id}/kernel` | 전체 | 릴리스·KMI generation·config 요약·모듈별 import/export 심볼 수 |
| GET | `/admin/v1/platforms/{id}/kernel/uprev?target_release=17` | 전체 | 목표 릴리스 지원 브랜치 중 현재 이상 후보(EOL·QPR 제외·지원 기간 충족·symbol list 등록 여부)와 `recommended` |
| GET | `/admin/v1/platforms/{id}/drivers?kernel_branch=` | 전체 | 드라이버 인벤토리: 서브시스템별 커널 드라이버(description·버스·ION 사용·vermagic 브랜치·`kmi_missing`)와 HAL(format·version). 분류는 추정이며 판정에는 쓰지 않음 |
| PUT | `/admin/v1/kernel/symbol-lists/{branch}` | engineer | KMI symbol list 파일들(multipart `files`, `source`) → 합집합 저장. 빈 vendor 파일은 허용, 전체가 비면 422 |
| GET | `/admin/v1/kernel/symbol-lists` | 전체 | 등록된 브랜치·심볼 수·파일·출처 |
| GET | `/admin/v1/readiness-runs/{id}` | 전체 | 결과·KB 버전. finding 은 `title`/`detail`(한국어)와 `title_en`/`detail_en`(영어, 도입 전 판정은 null) |
| PATCH | `/admin/v1/work-items/{id}` | engineer | 상태/담당/면제 사유 |
| POST | `/admin/v1/builds` | pipeline | 빌드 등록(fingerprint, timestamp, spl, sdk) |
| POST | `/admin/v1/packages` | pipeline | `{"object_key": "staging/…zip"}` 또는 multipart → 202 + ingest 작업 |
| GET | `/admin/v1/packages/{id}` | 전체 | 파싱 결과, status, reject_reasons |
| POST | `/admin/v1/packages/{id}/retire` | release_manager | 신규 할당 제외 |
| POST | `/admin/v1/rollouts` | release_manager | 롤아웃 생성(draft): target_build, channel, filters, stages[], halt_rules, policy |
| POST | `/admin/v1/rollouts/{id}/start` | release_manager | draft → active (stage 1 비율) |
| POST | `/admin/v1/rollouts/{id}/promote` | release_manager | 다음 stage. `min_soak_hours` 미충족 시 409 |
| POST | `/admin/v1/rollouts/{id}/pause` · `/resume` | operator | |
| POST | `/admin/v1/rollouts/{id}/halt` | operator | `{"reason": "..."}` |
| GET | `/admin/v1/rollouts/{id}/metrics` | 전체 | 스냅샷 시계열, 에러 코드 분포, fallback율 |
| GET | `/admin/v1/reports/delta-candidates?device=pony&target_build=…` | release_manager | 활성 기기 source fingerprint 분포 → incremental 생성 후보(OT-11) |

### 2.1 halt_rules 예시
```json
{
  "min_sample": 200,
  "max_error_rate": 0.03,
  "max_boot_fallback_rate": 0.005,
  "max_error_code_rate": {"60": 0.02, "61": 0.001},
  "window_minutes": 60
}
```
임계값 수치는 **예시**이며 조직 결정 사항(Q9). 평가 구현: `upgrade_core.rollout.evaluate_halt`.

### 2.2 기기 인벤토리와 배포 태그

`GET /admin/v1/devices?q=&device=&channel=&tag=&seen_within_hours=&limit=50&offset=0` →
`{items, total, limit, offset}`. limit은 1~200, offset은 0 이상이다. q는 기기 해시·모델·빌드의 대소문자 무시 부분 문자열이다.
같은 기기가 여러 번 체크인해도 items에는 최신 상태 한 건만 있다. 최근 체크인 필터는 연결 상태 판정이 아니다.

`GET /admin/v1/devices/summary` → `{total, seen_24h, models: [{device, devices}], tags: [{tag, devices}]}`.
`GET /admin/v1/devices/{hash}` → 최신 모델·채널·빌드·보안 패치·지역·태그·최초/최근 체크인과 assignments.
조회는 전체 관리자 API 역할에 허용한다.

`PUT /admin/v1/devices/{hash}/tags {"tags": ["canary", "lab-seoul"]}` → 상세 응답.
operator·release_manager·admin만 변경할 수 있다. 전체 태그 교체이며 빈 목록은 모두 제거한다. 중복은 제거하고 정렬한다.
대소문자를 구분한다. 기기당 최대 20개, 태그는 `^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}$`이며 변경은 감사 로그에 해시와 함께 남긴다.
기기 update-check 요청의 tags는 사용하지 않는다.

롤아웃 생성의 `filters.tags`는 하나 이상의 운영자 태그 일치를 요구하며, 기존 carrier·region·SKU·source 필터와 AND로 결합한다.
비어 있으면 태그 제한이 없다. 태그를 제거해도 offered/downloading/installed_pending_reboot 할당은 계속 유지한다.
필터에 맞는 롤아웃이 없으면 update-check reason은 `FILTER_MISMATCH`다.

### 2.3 배포 대상 미리보기와 단계 승격

`GET /admin/v1/rollouts/{id}/preview` →
`{rollout_id, mode, percent, total, eligible, reasons, packages: {full, incremental}, sample, as_of}`.
모델·채널이 같은 모든 기록된 기기의 최신 체크인을 대상으로 한다. 초안은 `mode=draft_first_stage`, 그 외는 `current_stage`다.
실제 매칭·재시도·재부팅 대기·중단 정책을 적용하며 저장 데이터를 변경하지 않는다. sample은 해시 순 최대 20건이다.
다른 롤아웃과의 우선순위와 아직 보고되지 않은 부팅 결과는 반영하지 않는다. reasons에는 `ELIGIBLE`,
`FILTER_MISMATCH`, `NOT_IN_ROLLOUT`, `UP_TO_DATE`, `NO_COMPATIBLE_PACKAGE`, `PENDING_REBOOT`,
`RETRY_LIMIT_REACHED`, `ROLLOUT_HALTED`, `ROLLOUT_INACTIVE`가 올 수 있다.

stage 입력은 `{percent, min_soak_hours, min_successful_boots: 0, min_success_rate: null}`이다.
성공 수는 0 이상, 성공률은 null 또는 0~1이다. 현재 stage의 조건은 **다음 단계로 승격할 때** 확인한다.
성공률은 전체 롤아웃에서 부팅 성공 / 설치 시도이며 이전 재시도 실패와 진행 중인 설치도 포함한다.
제안만 받은 할당과 일반 status만 있는 시도는 설치 시도에 포함하지 않는다. 설치 완료 후 재부팅 대기는 부팅 성공이 아니다.

`GET /admin/v1/rollouts/{id}/promotion-status` →
`{can_promote, reasons, soak_until, attempted, successful_boots, success_rate, min_successful_boots, min_success_rate, scope, rollout_id}`.
scope는 `rollout_all_attempts`, 표본이 없으면 success_rate는 null이다. reasons에는 `NOT_ACTIVE`, `FINAL_STAGE`,
`SOAK_PENDING`, `INSUFFICIENT_SUCCESSFUL_BOOTS`, `SUCCESS_RATE_BELOW_THRESHOLD`가 온다.
promote는 같은 저장소 락 안에서 조건을 다시 확인하고 미충족 시 409를 반환한다. 성공 조건 기본값 0·null은 기존 동작을 유지한다.
