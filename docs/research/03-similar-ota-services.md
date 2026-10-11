# Android OTA 유사 서비스와 기능 보강

Android OS 업그레이드 콘솔에는 패키지 검사와 단계 배포에 더해 기기별 현황과 대상 그룹을 관리하는 기능이 필요하다. 아래 서비스의 공개 저장소와 공식 문서를 비교해 기기 인벤토리, 운영자 태그, 배포 대상 미리보기, 승격 성공 조건을 보강했다. 비교 기준일은 2026-10-11이다.

## 유사 서비스 비교

| 서비스 | 범위와 확인한 기능 | 이 프로젝트에 적용할 점 | 1차 출처 |
|---|---|---|---|
| Eclipse hawkBit | 범용 기기 업데이트 서버. 대상 필터, 배포 그룹, 설치 성공 조건에 따른 순차 진행, 오류 임계값에 따른 중단, 선택적 승인 워크플로 | 기존 단계 배포·자동 중단에 그룹 필터와 승격 성공 조건 추가 | [GitHub](https://github.com/eclipse-hawkbit/hawkbit), [Rollouts Management](https://github.com/eclipse-hawkbit/hawkbit/wiki/Rollouts-Management) |
| Mender | 임베디드 Linux 중심의 기기·배포 관리. 클라이언트가 인벤토리 속성을 수집하고 서버로 보내 검색·정렬·필터에 사용 | 최신 체크인을 기기별로 조회하고 빌드·보안 패치·지역을 노출 | [GitHub server](https://github.com/mendersoftware/mender-server), [Inventory](https://docs.mender.io/client-installation/inventory) |
| LineageOTA | LineageOS Updater용 REST 서버. 로컬 full·delta 디렉터리, GitHub Releases를 통한 패키지 제공, 릴리스 개수·날짜 제한과 캐시 | 향후 CI 빌드 카탈로그·릴리스 노트 연동 참고. 패키지를 제공하는 형식만으로 Android A/B 호환성을 판단하지 않음 | [GitHub README](https://github.com/julianxhokaxhiu/LineageOTA#readme) |
| Aktualizr | Uptane 호환 OTA 서버와 통신하는 C++ 클라이언트. 기기 인증, 소프트웨어·하드웨어 정보 보고, 업데이트 확인·설치 결과 보고 | 향후 기기별 인증·서명 메타데이터 검증 설계 참고 | [GitHub README](https://github.com/advancedtelematic/aktualizr#readme) |

## 기능 선택 근거

현재 구현에는 Android A/B payload 검사, incremental 우선 매칭과 full 폴백, 안정적 해시 배포, 설치·부팅 결과 기록, 자동 중단, RBAC와 감사 로그가 있다. 플랫폼 준비도에는 VINTF·GKI·KMI·드라이버 검사가 있다. 이 범위에 대한 검토 결과, 우선 보강할 부분은 기기별 최신 상태 조회와 실제 배포 대상 확인이다. 범용 OTA 서버의 기능을 Android OTA 프로토콜로 교체하는 작업은 별도 범위다.

| 보강 기능 | 구현 | 동작 |
|---|---|---|
| 기기 인벤토리 | `backend/fleet.py`, `web/src/pages/Devices.tsx` | update-check의 최신 상태를 저장하고 해시·모델·빌드 검색, 모델·채널·태그·최근 체크인 필터, 페이지 이동, 설치 이력 조회 |
| 운영자 태그 | `PUT /admin/v1/devices/{hash}/tags` | operator·release_manager·admin이 관리. 기기 요청의 태그는 사용하지 않으며 변경은 감사 로그에 남김 |
| 태그별 배포 | `filters.tags` | 하나 이상의 태그 일치와 기존 속성 필터를 함께 적용. 진행 중인 할당에는 태그 제거를 적용하지 않음 |
| 대상 미리보기 | `GET /admin/v1/rollouts/{id}/preview` | 같은 모델·채널의 마지막 체크인에 실제 제공 로직 적용. 대상 수, full·incremental 수, 제외 사유와 최대 20개 기기 표시 |
| 승격 성공 조건 | stage의 `min_successful_boots`, `min_success_rate` | 유지 시간, 최소 부팅 성공 수, 성공률을 모두 만족해야 promote 허용. 미충족 시 409, 콘솔에 사유 표시 |

## 집계와 호환성

승격 성공률은 전체 롤아웃의 **부팅 성공 시도 수 / 설치 시도 수**다. 다운로드 시작, 설치 완료, 실제 실패 또는 부팅 결과가 있는 시도를 센다. 제안만 받은 기기와 일반 status 이벤트만 있는 시도는 분모에 포함하지 않는다. 설치 후 재부팅 대기는 성공에 포함하지 않으며 진행 중인 설치 시도와 이전 재시도의 실패도 집계한다. 현재 단계만의 성공률은 제공하지 않는다.

기존 SQLite 데이터베이스는 시작 시 최신 체크인에서 인벤토리를 한 번 가져오고, 기존 stage에 성공 수 0·성공률 null을 설정한다. 이 기본값은 새 성공 조건을 사용하지 않는다. 태그와 최초 체크인 시각은 다음 체크인에도 유지한다. 태그는 대소문자를 구분하며 영문·숫자로 시작하고 점·밑줄·하이픈을 포함해 최대 32자, 기기당 최대 20개다.

미리보기는 체크인·assignment·이벤트·감사 로그를 생성하지 않는다. 초안은 첫 단계 비율을 사용하고, 시작 이후에는 현재 단계·상태를 사용한다. 재부팅 대기, 최대 재시도, pause·halt 정책도 반영한다. 다른 롤아웃과의 우선순위, 다음 체크인에서 새로 판정할 부팅 결과, 향후 기기 유입은 예측하지 않는다. 기록된 체크인에는 시효 제한이 없어 오래된 기기도 포함될 수 있다.

## 후속 기능

| 우선순위 | 기능 | 필요한 설계 |
|---|---|---|
| 높음 | 기기별 인증 | 공유 기기 키를 대신할 발급·회수·갱신 체계와 기기 식별 계약 |
| 높음 | 단계별 독립 집계 | assignment의 시도별 단계 귀속을 저장하고 단계 승격 시 집계 범위를 명확히 정의 |
| 중간 | 배포 승인과 예약 | 역할 분리, 예약 시각·시간대, 승인 후 변경 시 무효화 규칙 |
| 중간 | CI 릴리스 카탈로그 | 빌드 산출물·서명·릴리스 노트 계약, GitHub Releases/CDN 오리진의 Range·리다이렉트 동작 |
| 중간 | 서명 메타데이터 | 기기와 서버가 함께 검증하는 신뢰 체계. Aktualizr의 Uptane 설계를 참고하되 Android Updater 계약에 맞게 검토 |

원격 터미널, MQTT 전달, 자동 단계 승격, 서비스 간 프로토콜 호환은 이번 보강에 포함하지 않았다. 실기기 설치 검증과 운영 DB 전환은 기존 구현 계획의 후속 작업이다.
