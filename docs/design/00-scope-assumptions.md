# 00. 범위 · 가정 · 결정 필요 사항

작성일: 2026-09-14 · 상태: 초안(사전 작업)

## 1. 요청

> "Android OS upgrade를 할거야. 필요한 정보를 취합해서 backend 구현을 위한 사전 작업을 진행해 줘"

요청에 backend의 성격이 명시되지 않아, 아래 가정으로 진행했다. **가정이 틀리면 §3의 질문부터 확정**하고 02~05 문서를 조정한다.

## 2. 가정

| # | 가정 | 근거 |
|---|---|---|
| A1 | 대상은 **자사(또는 고객사) 기기/BSP의 Android 메이저 버전 업그레이드** (예: 16 → 17). 앱 targetSdk 업그레이드가 아님 | 인접 프로젝트(camera-hal-dev 등)가 SoC/HAL 레벨 엔지니어링 도구 |
| A2 | backend는 두 도메인을 담당한다<br>① **Upgrade Readiness** — 플랫폼/기기별 업그레이드 가능 여부·작업 항목 판정(커널·FCM·VNDK·HAL·16KB 등)<br>② **OTA Delivery** — 빌드된 OTA 패키지를 등록·매칭·단계 배포·텔레메트리 수집 | OS 업그레이드는 "준비(개발)"와 "배포(전달)" 두 단계로 나뉨 |
| A3 | 기기 측 업데이트 클라이언트는 OEM privileged 앱이 `UpdateEngine.applyPayload()` 를 호출하는 구조(A/B·Virtual A/B). Non-A/B는 지원하지 않음 | Android 13+ launch 기기는 Virtual A/B ([research/02 §1.6](../research/02-ota-delivery-mechanics.md)) |
| A4 | 서명(release keys, AVB)은 backend 밖(빌드 파이프라인/HSM)에서 수행. backend는 **서명된 산출물만** 받는다 | 키 노출 최소화 원칙 |
| A5 | 기술 스택은 인접 프로젝트 관례를 따름: Python ≥ 3.10, 표준 라이브러리 코어 + FastAPI/pydantic API 계층, PostgreSQL(운영) / SQLite(개발) | camera-hal-dev 구조 |
| A6 | Mainline(APEX) 모듈 배포는 범위 밖(텔레메트리 수집만) | Play System Update는 별도 채널 |

## 3. 확인이 필요한 질문 (Open Questions)

| # | 질문 | 영향 문서 |
|---|---|---|
| Q1 | backend 범위가 ①Readiness ②OTA Delivery 둘 다인가, 하나인가? | 01, 02, 05 |
| Q2 | 업그레이드 대상: 몇 개 SoC/플랫폼, 몇 개 기기 모델, 출하 기기 대수 규모? | 02(용량), 03 |
| Q3 | 현재 → 목표 버전 (예: Android 15/16 → 17 또는 17 QPR2)? 목표 기준선이 AOSP 26Q2 공개본인가 파트너 채널 QPR1인가? | 01 |
| Q4 | 현 기기 커널 브랜치 (특히 android12/13-5.10 사용 여부 — Android 17 QPR1+ 미지원) | 01 |
| Q5 | GRF/vendor freeze 적용(vendor 이미지 유지, system-only 업그레이드) 여부 | 01, 03 |
| Q6 | 기기 인증 방식: 기기별 인증서(mTLS)/Key Attestation/사전 발급 토큰 중 무엇이 가능한가? | 04 |
| Q7 | 배포 인프라: 사내 온프레미스 / 클라우드(CDN) / 폐쇄망? HTTP Range 지원 오리진 가능 여부 | 02 |
| Q8 | 기존 연동 시스템: Jira/Confluence(작업 항목), 빌드 시스템(Jenkins 등), 크래시 수집? | 02, 05 |
| Q9 | 단계 배포 halt 임계값을 누가 결정·승인하는가(운영 조직, 승인 워크플로 필요 여부)? | 01, 04 |

## 4. 산출물 목록

| 문서 | 내용 |
|---|---|
| [research/01](../research/01-platform-upgrade-requirements.md) | 플랫폼 업그레이드 요구사항(릴리스·GKI·Treble·인증·체크리스트) |
| [research/02](../research/02-ota-delivery-mechanics.md) | OTA 전달 메커니즘(A/B·VABC·payload·update_engine·보안·서버) |
| [01-requirements](01-requirements.md) | 기능/비기능 요구사항 |
| [02-architecture](02-architecture.md) | 컴포넌트·흐름·배포 구조 |
| [03-data-model](03-data-model.md) | 엔터티·스키마 |
| [04-api-spec](04-api-spec.md) | 기기용/운영용 API 계약 |
| [05-implementation-plan](05-implementation-plan.md) | 단계별 구현 계획·리스크 |
| `upgrade_core/` | 표준 라이브러리 코어(파서·매칭·호환성 판정) + 테스트 |
