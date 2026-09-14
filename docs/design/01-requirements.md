# 01. 요구사항

근거 문서: [research/01](../research/01-platform-upgrade-requirements.md), [research/02](../research/02-ota-delivery-mechanics.md). 우선순위: **M**(MVP 필수) / **S**(2단계) / **C**(선택).

## 1. 액터

| 액터 | 설명 |
|---|---|
| BSP/플랫폼 엔지니어 | 플랫폼 프로파일 등록, readiness 결과 확인, 작업 항목 처리 |
| 릴리스 매니저 | 빌드/패키지 등록, 롤아웃 생성·승격·중단 |
| 기기(Updater 앱) | 업데이트 확인, 설치 이벤트 보고 |
| 빌드 파이프라인 | 서명된 OTA 패키지 업로드(서비스 계정) |
| 운영자 | 대시보드·경보 확인, 자동 halt 대응 |

## 2. 기능 요구사항 — ① Upgrade Readiness

| ID | 요구사항 | 우선 |
|---|---|---|
| RD-01 | Android 릴리스 지식베이스 관리: 버전·API 레벨·FCM/vendor API 레벨·지원 커널 목록·ACK EOL·CTS 리비전. 각 항목에 **출처 URL과 신뢰도(1차/2차/미확인)** 저장 | M |
| RD-02 | 플랫폼 프로파일 등록: SoC, 기기 모델, `ro.product.first_api_level`, `ro.board.api_level`, `ro.board.api_frozen`, 현재 Android 버전, 커널 ACK 브랜치, FCM target level, page size, VNDK 사용 여부, ION 사용 여부, HAL 목록(HIDL/AIDL + 버전) | M |
| RD-03 | Readiness 판정: (플랫폼, 목표 릴리스) → 규칙 평가 → `blocker/warning/info` finding 목록. 최소 규칙: 커널 호환 매트릭스, 커널 EOL vs 지원 종료 목표일, ION 사용, VNDK 의존(15+), HIDL HAL 잔존, 16KB 준비, SELinux memfd(17) | M |
| RD-04 | 규칙은 코드가 아닌 **데이터(버전 관리되는 JSON) + 소수의 판정 함수**로 정의해 릴리스마다 갱신 가능 | M |
| RD-05 | Finding → 작업 항목(체크리스트) 생성, 상태 추적(todo/in_progress/done/waived + 사유) | S |
| RD-06 | 작업 항목을 Jira 이슈로 내보내기(camera-hal-analysis 형식 참조) | C |
| RD-07 | 두 FCM `compatibility_matrix.<level>.xml` diff 업로드 → 제거/버전업 HAL 목록 추출 | S |

## 3. 기능 요구사항 — ② OTA Delivery

| ID | 요구사항 | 우선 |
|---|---|---|
| OT-01 | OTA 패키지 등록: zip 업로드(또는 오리진 URL 등록) 시 `META-INF/com/android/metadata`(+`metadata.pb`), `payload_properties.txt`, zip 엔트리 offset/size를 **서버가 직접 파싱**해 저장. 수동 입력 금지 | M |
| OT-02 | 등록 검증: `ota-type=AB`, payload.bin STORED 여부, post-timestamp/SPL 존재, `downgrade`/`wipe`/`spl-downgrade` 플래그 기록, 파일 sha256 계산 | M |
| OT-03 | 빌드 계보: device별 build(fingerprint, incremental, timestamp, SPL, SDK) 등록, full/incremental 패키지를 (device, source, target)로 연결 | M |
| OT-04 | 업데이트 확인 API: 기기 상태 → 제공 가능 패키지 선택. 규칙: device 일치 ∧ (incremental이면 source fingerprint ∈ pre-build) ∧ post_timestamp > 현재 ∧ post_spl ≥ 현재 ∧ 롤아웃 대상. incremental 우선, 없으면 full 폴백 | M |
| OT-05 | 응답은 `applyPayload(url, offset, size, headers[])` 에 바로 넣을 수 있는 형태(§04 API) | M |
| OT-06 | 롤아웃: 채널(testing/beta/stable), 대상 필터(device, carrier/region/SKU, 현재 빌드), 단계 비율, **안정적 해시 버킷**(비율 증가 시 기존 대상 유지) | M |
| OT-07 | 롤아웃 상태 머신: draft → active ⇄ paused → completed / halted. 상태 전이 감사 로그 | M |
| OT-08 | 텔레메트리 수신: check, download_start, status 전이, error(native ErrorCode 0~66 + 플래그 비트 원형 저장), updated_need_reboot, post-reboot checkin(fingerprint) | M |
| OT-09 | 부팅 성공/폴백 판정: 설치 완료 후 첫 체크인 fingerprint == post-build → success, == pre-build → fallback | M |
| OT-10 | 자동 halt: 롤아웃별 임계값(에러율, fallback율, NOT_ENOUGH_SPACE 비율 등) 초과 시 **신규 할당 중단** + 알림. 이미 적용된 기기는 되돌릴 수 없으므로 roll-forward 전제 | S |
| OT-11 | Delta 우선순위 리포트: 활성 기기의 source fingerprint 분포 → 생성할 incremental 목록 제안 | S |
| OT-12 | 2단계 활성화: `SWITCH_SLOT_ON_REBOOT=false` 로 선적용 후 서버 신호로 슬롯 전환 | C |
| OT-13 | 배포 불가 조합 차단: target timestamp/SPL < source 인 패키지는 롤아웃 편입 금지(downgrade 플래그 명시적 승인 시 예외) | M |

## 4. 비기능 요구사항

| ID | 요구사항 |
|---|---|
| NF-01 보안 | 기기 API는 기기 인증 필수(Q6에 따라 mTLS 또는 서명 토큰). 운영 API는 SSO/RBAC(엔지니어·릴리스매니저·운영자·서비스계정). 서명 키는 backend에 두지 않음 |
| NF-02 무결성 | 패키지 파일은 불변(immutable) 경로·이름(빌드ID/해시 포함). 등록 후 파일 교체 금지 → update_engine resume(payload_id) 보장 |
| NF-03 전달 | 오리진/CDN은 HTTP Range 지원, 캐시 키는 URL만. 다운로드 트래픽은 backend를 거치지 않음(서명 URL 또는 AUTHORIZATION 헤더) |
| NF-04 가용성 | update-check 실패 시 기기는 backoff 후 재시도해야 하므로 check API는 무상태·수평 확장. 응답에 `next_check_after_s`(scatter 포함) |
| NF-05 성능 | update-check p95 < 200ms(DB 인덱스 조회 1~2회 + 해시 계산). 이벤트 수집은 비동기 적재 |
| NF-06 감사 | 롤아웃 생성/승격/halt, 패키지 등록/폐기, 규칙셋 변경은 감사 로그 |
| NF-07 개인정보 | 기기 식별자는 해시로만 저장, IMEI/시리얼 원문 금지. 이벤트 보존 기간 설정 |
| NF-08 추적성 | 지식베이스·규칙 판정 결과는 출처와 규칙셋 버전을 함께 저장(재현 가능) |
| NF-09 테스트 | 코어 로직(파싱·매칭·버킷·판정)은 외부 의존 없는 단위 테스트로 검증 |

## 5. 범위 밖

- OTA 패키지 생성(`ota_from_target_files`)·서명 — 빌드 파이프라인 책임
- 기기 측 Updater 앱 구현(API 계약만 정의)
- Mainline/APEX 배포, 앱 스토어 배포
- 파트너 전용 문서(VSR, GMS 요구사항) 내용 — 접근 권한 확보 후 지식베이스에 반영
