# 02. Android OS OTA 전달 메커니즘 (백엔드 설계 관점)

- 작성일: 2026-09-14
- 목적: OS 버전 업그레이드용 OTA 업데이트 서버 + 롤아웃 관리 백엔드 설계를 위한 사전 조사
- 방법: source.android.com, developer/AOSP googlesource 소스(update_engine, releasetools, libsnapshot, avb), Omaha 프로토콜 문서, 오픈소스 업데이터(LineageOS, GrapheneOS)를 WebFetch/WebSearch로 확인
- 표기 규칙: 1차 출처에서 확인하지 못한 내용은 **(미확인)**, 소스 코드를 읽고 추론한 내용은 **(코드 기반 추론)** 으로 표기. 수치는 출처에 있는 것만 인용.

---

## 0. 요약 (Executive Summary)

1. 현대 Android 기기(Android 11+ 출시 GMS 기기)는 **Virtual A/B** 가 필수이며, 기기 측 설치는 `update_engine` 이 담당한다. Android에서는 Chrome OS와 달리 **update_engine이 서버에 직접 질의하지 않고**, OEM의 privileged 앱이 서버와 통신한 뒤 `UpdateEngine.applyPayload(url, offset, size, headers[])` 로 설치를 위임한다. 따라서 **서버 API 계약(업데이트 확인 → 페이로드 URL/offset/size/headers 반환)은 OEM이 자유롭게 설계**한다.
2. OTA 패키지(zip)는 `ota_from_target_files` 로 생성되며 핵심은 `payload.bin` + `payload_properties.txt`(FILE_HASH, FILE_SIZE, METADATA_HASH, METADATA_SIZE) + `META-INF/com/android/metadata(.pb)`(pre/post 조건). 서버는 이 값들을 **빌드 파이프라인에서 추출해 DB에 저장**해야 한다.
3. 스트리밍 설치 시 update_engine은 zip 내부의 `payload.bin` 을 offset/size로 직접 읽는다 → **CDN/오리진은 HTTP Range 요청을 지원**해야 한다(코드 기반 추론, 아래 참고).
4. 서버는 기기의 **source build fingerprint/incremental** 에 맞춰 incremental(delta) 또는 full 패키지를 골라야 하고, pre-build 불일치 시 설치가 실패하므로 **delta 매트릭스 관리가 필수**다.
5. 다운그레이드는 기기 측에서 `max_timestamp`, 파티션 버전, SPL, AVB rollback index로 다중 차단된다 → 서버의 "롤백"은 사실상 **더 새로운 빌드(roll-forward)** 로 해야 한다.
6. Mainline(APEX/APK) 모듈 업데이트는 Google Play 시스템 업데이트 또는 파트너 OTA로 전달되는 **별개 채널**이다.

---

## 1. 업데이트 방식 (Update Types)

### 1.1 Non-A/B (Legacy)
- recovery 파티션에 별도의 Linux 시스템(kernel + recovery 바이너리)이 있고, `/cache` 에 패키지를 받아 recovery로 재부팅하여 `META-INF/com/google/android/update-binary` 를 실행해 적용한다.
- 공식 문서에서 **"deprecated OTA methodology"** 로 명시.
- 설치 중 기기 사용 불가, 실패 시 기기 벽돌화 위험.
- 출처: https://source.android.com/docs/core/ota/nonab

### 1.2 A/B (Seamless)
- 두 슬롯(A/B)을 유지하고 비활성 슬롯에 기록. 설치 중 정상 사용 가능, 재부팅만 다운타임.
- 라이프사이클(공식 문서 9단계):
  1. 현재 슬롯 `markBootSuccessful()`
  2. 대상 슬롯 `setSlotAsUnbootable()`
  3. payload metadata 다운로드
  4. operation 순차 적용
  5. 파티션 해시 검증
  6. postinstall 준비
  7. `setActiveBootSlot()`
  8. 새 버전에서 postinstall 실행
  9. 새 슬롯 부팅 성공 시 successful 마킹
- `boot_control` HAL: bootable/successful/active 속성. 새 슬롯이 부팅 실패하면 **부트로더가 이전 슬롯으로 자동 폴백**.
- 스트리밍 A/B: 블록을 대상 파티션에 직접 기록하므로 패키지 전체 임시 저장 불필요, metadata는 약 100 KiB.
- 출처: https://source.android.com/docs/core/ota/ab , https://source.android.com/docs/core/ota/ab/ab_faqs

### 1.3 Dynamic Partitions (super)
- `super` 파티션 내부에 `system`, `vendor`, `product` 등을 동적 생성/리사이즈. OTA 시 파티션 크기 변경 가능.
- Android 10 출시 기기는 `super` 파티션 생성(dynamic partitions). 기존 기기는 `--retrofit_dynamic_partitions` 로 전환 가능.
- 출처: https://source.android.com/docs/core/ota/dynamic_partitions , https://source.android.com/docs/core/ota/dynamic_partitions/implement

### 1.4 Virtual A/B
- **Android 11 이상 출시 GMS 기기의 필수 요구사항**. A/B로 구성되어야 하며 dynamic partitions로 출시해야 함.
- 부트로더가 쓰는 파티션만 물리적으로 이중화하고, 나머지 업데이트 파티션은 **snapshot(COW)** 으로 처리 → `BOARD_SUPER_PARTITION_SIZE` 는 한 슬롯분만 필요.
- 재부팅 후 snapshot을 base 디바이스에 **merge**. Android 13(T)+에서는 merge가 전적으로 userspace(`snapuserd` + `dm-user`)에서 이뤄지며, 중단 시 재부팅 후 재개 가능.
- Android 13 출시 기기: VTS로 "userspace snapshots 기반 Virtual A/B" 가 사실상 강제되며 compression은 필수 아님(2차 출처 Esper, 1차 문서로는 **(미확인)**). GRF 예외 존재.
- 레거시 기기 userspace snapshot 활성화: `ro.virtual_ab.userspace.snapshots.enabled=true`
- 커널 요구: `CONFIG_DM_SNAPSHOT`, compressed snapshot 시 `CONFIG_DM_USER`; Boot Control HAL 1.1+ (snapshot merge status API).
- 출처: https://source.android.com/docs/core/ota/virtual_ab , https://source.android.com/docs/core/ota/virtual_ab/implement , https://www.esper.io/blog/android-13-virtual-ab-requirement

### 1.5 Virtual A/B Compression (VABC)
- COW operation: Copy, Replace, Zero, XOR(Android 13+).
- 압축 알고리즘:
  - 기기 빌드 설정 문서상 지원: `zstd`, `lz4` (`PRODUCT_VIRTUAL_AB_COMPRESSION_METHOD`)
  - `ota_from_target_files --vabc_compression_param`: `gz, lz4, zstd, brotli, none`
  - libsnapshot `CowCompressionAlgorithm`: None(0), Gz(1), Brotli(2), Lz4(3), Zstd(4)
- Compression factor(최대 압축 윈도우): 기본 64k, `PRODUCT_VIRTUAL_AB_COMPRESSION_FACTOR` 로 4k~256k (`2^n * 4096`).
- COW 버전: libsnapshot `cow_format.h` 에서 min 1, max **3**. v3는 `CowOperationV3` 로 operation 메타데이터를 64-bit `source_info` 에 패킹한 경량 포맷. `--vabc_cow_version` 으로 생성 시 지정. v3의 최초 도입 릴리스 **(미확인, Android 15로 알려져 있으나 1차 출처 미확인)**.
- 공식 수치:
  - 압축 시 snapshot 크기: full OTA 약 45% 감소, incremental OTA 약 55% 감소. 예시 기기 총 필요 공간 8.3GB → 6.6GB.
  - Pixel 8 Pro incremental: 무압축 4.76GB/약 17분, lz4 2.5GB/약 18분, zstd 2.05GB/약 25분.
  - io_uring 사용 시 merge 시간 약 40% 감소(LPC 2022 발표).
- Android 13+ 기기 설정: `generic_ramdisk.mk`, `virtual_ab_ota/vabc_features.mk` 상속. snapuserd는 Android 13에서 vendor ramdisk → generic ramdisk로 이동.
- 백엔드 영향: VABC/XOR/압축 알고리즘 선택은 **설치 시간·필요 여유 공간**에 영향 → 서버가 기기 여유 공간 부족(`NOT_ENOUGH_SPACE`=60) 에러를 집계해야 함.
- 출처: https://source.android.com/docs/core/ota/virtual_ab/implement , https://android.googlesource.com/platform/system/core/+/refs/heads/main/fs_mgr/libsnapshot/include/libsnapshot/cow_format.h , https://lpc.events/event/16/contributions/1331/attachments/951/1867/LPC2022%20-%20io_uring%20in%20Android%20OTA.pdf

### 1.6 릴리스별 요구사항 요약

| 출시 Android | 요구사항 | 근거 |
|---|---|---|
| ≤ 6 | Non-A/B (deprecated) | nonab 문서 |
| 10 | dynamic partitions(`super`) | dynamic_partitions/implement |
| 11 | Virtual A/B (GMS 요구) | virtual_ab 문서 |
| 13 | userspace snapshot 기반 VAB (VTS), compression 선택 | Esper(2차) — 1차 **(미확인)** |
| 15+ | COW v3 등 | **(미확인)** |

---

## 2. 패키지 생성 (Package Generation)

### 2.1 target-files와 서명 파이프라인
1. 빌드 → `*-target_files.zip`
2. `sign_target_files_apks --default_key_mappings <keys> unsigned-target_files.zip signed-target_files.zip`
3. `ota_from_target_files -k <releasekey> signed-target_files.zip ota.zip`
4. (팩토리 이미지) `img_from_target_files`
- 출처: https://source.android.com/docs/core/ota/sign_builds , https://source.android.com/docs/core/ota/tools

### 2.2 Full vs Incremental
- Full: 기기 상태와 무관하게 설치 가능한 전체 최종 상태.
  `ota_from_target_files target_files.zip ota_update.zip`
- Incremental(delta): 기기에 있는 데이터에 대한 바이너리 패치. **정확한 source 빌드가 필요**.
  `ota_from_target_files -i PREVIOUS-target_files.zip NEW-target_files.zip incremental.zip`
- Delta 크기 절감 기법: puffin(deflate 재압축 diff), bsdiff, brotli, `--enable_zucchini`, `--enable_lz4diff`(EROFS), 재현 가능 빌드, on-device verity 계산(2GB 파티션당 약 16MB 절감).
- 출처: https://source.android.com/docs/core/ota/tools , https://source.android.com/docs/core/ota/reduce_size

### 2.3 주요 `ota_from_target_files` 플래그 (docstring 기준)

| 플래그 | 의미 |
|---|---|
| `-i` | incremental source target-files |
| `-k` | 패키지 서명 키 |
| `--downgrade` | 신→구 incremental 생성, **data wipe 강제**, `ota-downgrade=yes` |
| `--override_timestamp` | 역순 컷된 빌드 대응, wipe 없이 타임스탬프 우회 |
| `--wipe_user_data` | 설치 시 userdata 초기화 |
| `--spl_downgrade` | 대상 빌드 SPL이 더 오래된 경우 강제 생성 |
| `--partial` | `ab_partitions` 를 지정 목록으로 제한(부분 업데이트) |
| `--retrofit_dynamic_partitions` | dynamic partitions 전환용 |
| `--include_secondary` | secondary slot 이미지 페이로드 포함 |
| `--skip_postinstall` | postinstall hook 생략 |
| `--payload_signer` | payload/metadata 서명자 지정(HSM 등) |
| `--max_timestamp` | payload 적용 가능한 최대 timestamp |
| `--vabc_compression_param` | gz/lz4/zstd/brotli/none (+레벨) |
| `--vabc_cow_version` | COW 버전 |
| `--enable_vabc_xor` | 공간 감소, 설치 느려짐 |
| `--force_minor_version` | update_engine minor version 강제 |
| `--security_patch_level` | target files SPL override |
| `--full_radio` | incremental에 radio 전체 포함 |

출처: https://android.googlesource.com/platform/build/+/refs/heads/main/tools/releasetools/ota_from_target_files.py

### 2.4 A/B OTA zip 구조

| 엔트리 | 내용 |
|---|---|
| `payload.bin` | update_engine 페이로드 (`CrAU` magic) |
| `payload_properties.txt` | `FILE_HASH`, `FILE_SIZE`, `METADATA_HASH`, `METADATA_SIZE` (key=value) |
| `META-INF/com/android/metadata` | 레거시 텍스트 metadata |
| `META-INF/com/android/metadata.pb` | `OtaMetadata` protobuf |
| `care_map.pb` / `care_map.txt` | verity 대상 블록 맵 (optional) |
| `apex_info.pb` | 압축 APEX 정보 (optional) |
| `compatibility.zip` | (optional, 레거시) |

- `FILE_HASH` 는 base64로 디코드됨(update_engine 코드). 해시 알고리즘은 SHA-256 **(코드 기반 추론)**.
- Property files 문자열 형식: `name:offset:size` 콤마 구분.
  - `ota-streaming-property-files`: 필수 `payload.bin`, `payload_properties.txt`; 선택 `apex_info.pb`, `care_map.pb`, `care_map.txt`, `compatibility.zip`
  - `ota-property-files`: 위 + `payload_metadata.bin`(payload header/manifest 부분) + `metadata`
- 스트리밍 설치를 위해 `payload.bin` 외 엔트리는 `ZIP_STORED`(무압축)여야 offset으로 접근 가능(SystemUpdaterSample README). payload.bin 자체도 STORED로 저장되어야 offset 스트리밍이 가능하다 **(코드 기반 추론)**.
- 출처: https://android.googlesource.com/platform/build/+/refs/heads/main/tools/releasetools/ota_utils.py , https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/common/constants.h , https://android.googlesource.com/platform/bootable/recovery/+/refs/heads/main/updater_sample/README.md

### 2.5 payload.bin 구조 (update_metadata.proto)
- Header: `"CrAU"` magic → `file_format_version` → `manifest_size` → (v2+) `metadata_signature_size` → `DeltaArchiveManifest` → metadata signature → data blobs → payload signatures.
- `DeltaArchiveManifest` 주요 필드:
  - `minor_version` (0=full, 그 외 delta)
  - `max_timestamp` — "The maximum timestamp of the OS allowed to apply this payload. Can be used to prevent downgrading the OS."
  - `security_patch_level` (yyyy-mm-dd)
  - `partial_update`
  - `dynamic_partition_metadata`: `vabc_enabled`, `vabc_compression_param`, `cow_version`, `compression_factor`
  - `apex_info`
  - `PartitionUpdate.version`: 대부분 build timestamp
- 출처: https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/update_metadata.proto

### 2.6 OtaMetadata (metadata.pb)

```proto
enum OtaType { UNKNOWN = 0; AB = 1; BLOCK = 2; BRICK = 3; }
message PartitionState { string partition_name = 1; repeated string device = 2; repeated string build = 3; string version = 4; }
message DeviceState {
  repeated string device = 1; repeated string build = 2; string build_incremental = 3;
  int64 timestamp = 4; string sdk_level = 5; string security_patch_level = 6;
  repeated PartitionState partition_state = 7;
}
message OtaMetadata {
  OtaType type = 1; bool wipe = 2; bool downgrade = 3;
  map<string, string> property_files = 4;
  DeviceState precondition = 5; DeviceState postcondition = 6;
  bool retrofit_dynamic_partitions = 7; int64 required_cache = 8; bool spl_downgrade = 9;
}
```
- 레거시 텍스트 필드: `ota-type`, `ota-wipe`, `ota-downgrade`, `pre-device`, `pre-build`, `pre-build-incremental`, `post-build`, `post-build-incremental`, `post-timestamp`, `post-sdk-level`, `post-security-patch-level`, `spl-downgrade`. Multi-SKU는 `|` 로 여러 fingerprint 구분.
- 다운그레이드 감지: `ro.build.date.utc` 비교(A/B는 파티션별 timestamp도). 감지되었는데 `--downgrade` 없으면 빌드 실패.
- **백엔드 활용**: 업로드 시 `metadata.pb` 를 파싱해 `precondition.build`(source fingerprint 목록), `postcondition.build`, `timestamp`, `security_patch_level`, `sdk_level`, `wipe`, `downgrade`, `spl_downgrade`, `property_files` 를 DB 컬럼으로 저장하면 서버 매칭 로직을 metadata에서 직접 구동할 수 있다.
- 출처: https://android.googlesource.com/platform/build/+/refs/heads/main/tools/releasetools/ota_metadata.proto , https://source.android.com/docs/core/ota/tools

---

## 3. 기기 측 클라이언트

### 3.1 역할 분담 (Android)
- `update_engine`(데몬): 파티션 읽기/쓰기, `boot_control` 호출, postinstall 실행. SELinux로 파티션 테이블/현재 슬롯 수정 불가.
- Android용 update_engine(`aosp/update_attempter_android.cc`)은 **Omaha 질의 없이** 클라이언트가 전달한 URL/헤더로 동작. 업데이트 확인·정책·UI는 OEM의 privileged 시스템 앱 책임 **(코드 기반 추론 — Omaha 코드는 `cros/` 디렉터리에 분리)**.

### 3.2 `android.os.UpdateEngine` (@SystemApi)
| 메서드 | 설명 |
|---|---|
| `bind(UpdateEngineCallback[, Handler])` | 상태/완료 콜백 등록 |
| `applyPayload(String url, long offset, long size, String[] headerKeyValuePairs)` | URL(http/https/file) 내 offset/size 영역을 payload로 적용 |
| `applyPayload(AssetFileDescriptor, String[])` | fd 기반 적용 |
| `cancel()` / `suspend()` / `resume()` | 취소/일시정지/재개 |
| `resetStatus()` | 비활성 슬롯 bootable 플래그 및 내부 상태 리셋 |
| `verifyPayloadMetadata(String file)` | 적용 가능 여부 사전 검증 |
| `allocateSpace(String metadataFile, String[] headers)` → `AllocateSpaceResult` | 사전 공간 할당(@WorkerThread) |
| `cleanupAppliedPayload()` | 이전 업데이트 파일 정리 / merge 대기(@WorkerThread) |
| `setShouldSwitchSlotOnReboot(String metadataFile)` / `resetShouldSwitchSlotOnReboot()` | 슬롯 전환 제어 |
| `triggerPostinstall(String partition)` | @FlaggedApi, 파티션 postinstall 실행 |
| `unbind()` | 콜백 해제 |

- 출처: https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/os/UpdateEngine.java
- 필요 권한/SELinux 정책 상세 **(미확인)** — 샘플앱은 `/system/priv-app` 설치 + `privapp-permissions-platform.xml` 화이트리스트 권장.

### 3.3 applyPayload 헤더 키 (`common/constants.h`)

| 키 | 용도 |
|---|---|
| `FILE_HASH`, `FILE_SIZE` | payload 해시(base64)/크기 |
| `METADATA_HASH`, `METADATA_SIZE` | metadata 해시/크기 |
| `AUTHORIZATION` | HTTP `Authorization` 헤더로 전달 |
| `USER_AGENT` | User-Agent |
| `HTTP_EXTRAS` | 추가 HTTP 헤더 |
| `POWERWASH` | 설치 후 data wipe |
| `SPL_DOWNGRADE` | SPL 다운그레이드 허용 표시 |
| `NETWORK_ID`, `NETWORK_PROXY` | 네트워크 바인딩/프록시 |
| `SWITCH_SLOT_ON_REBOOT` | 기본 true; false면 적용만 하고 슬롯 전환 보류 |
| `RUN_POST_INSTALL` | postinstall 실행 여부 |
| `DOWNLOAD_RETRY` | libcurl 재시도 횟수 |
| `DISABLE_VABC`, `VABC_NONE`, `ENABLE_THREADING`, `BATCHED_WRITES` | VABC 동작 제어 |

- 재시도 기본 상수: `kDownloadMaxRetryCount = 20`, 인터랙티브 3.
- Resume: `FILE_HASH`+`METADATA_HASH` 로 payload_id를 만들고 이전 진행 상태와 같으면 이어서 설치 → **서버는 같은 빌드에 대해 payload 해시를 안정적으로 유지해야** 재개가 동작.
- 공식 빌드에서 해시 검증 필수(`hash_checks_mandatory = IsOfficialBuild()`).
- 일반적 호출 형태: `payload_properties.txt` 의 각 줄 + `USER_AGENT=...` + `AUTHORIZATION=...` 등을 `String[]` 로 전달.
- 출처: https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/common/constants.h , https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/aosp/update_attempter_android.cc

### 3.4 상태/에러 코드

UpdateStatusConstants: IDLE 0, CHECKING_FOR_UPDATE 1, UPDATE_AVAILABLE 2, DOWNLOADING 3, VERIFYING 4, FINALIZING 5, UPDATED_NEED_REBOOT 6, REPORTING_ERROR_EVENT 7, ATTEMPTING_ROLLBACK 8, DISABLED 9

ErrorCodeConstants(공개 SystemApi 일부): SUCCESS 0, ERROR 1, FILESYSTEM_COPIER_ERROR 4, POST_INSTALL_RUNNER_ERROR 5, PAYLOAD_MISMATCHED_TYPE_ERROR 6, INSTALL_DEVICE_OPEN_ERROR 7, KERNEL_DEVICE_OPEN_ERROR 8, DOWNLOAD_TRANSFER_ERROR 9, PAYLOAD_HASH_MISMATCH_ERROR 10, PAYLOAD_SIZE_MISMATCH_ERROR 11, DOWNLOAD_PAYLOAD_VERIFICATION_ERROR 12, PAYLOAD_TIMESTAMP_ERROR 51, UPDATED_BUT_NOT_ACTIVE 52, NOT_ENOUGH_SPACE 60, DEVICE_CORRUPTED 61

native `ErrorCode`(error_code.h)는 0~66까지 더 세분화(예: 21 InvalidMetadataMagicString, 24~26 metadata signature 오류, 44/45 Unsupported major/minor version, 48 UserCanceled, 57 InternalLibCurlError, 62 PackageExcludedFromUpdate, 63 PostInstallMountError, 64 OverlayfsenabledError, 65 UpdateProcessing, 66 UpdateAlreadyInstalled) 및 플래그 비트(DevMode 1<<31, Resumed 1<<30 등).
→ **서버 텔레메트리 스키마는 native 전체 코드 + 플래그 비트를 수용**하도록 설계 권장.

출처: https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/common/error_code.h

### 3.5 매니페스트 검증(기기 측 거부 조건, `delta_performer.cc`)
- 현재 OS build timestamp > `max_timestamp` → `kPayloadTimestampError`(51).
- `PartitionUpdate.version` 이 기기 파티션보다 오래되면 거부(partial update는 모든 파티션 timestamp 필수).
- `CheckSPLDowngrade()`: target SPL < `ro.build.version.security_patch` 이고 verified boot state가 green(잠긴 부트로더)이면 거부.
- minor version이 지원 범위 밖이면 거부 → **구형 기기에 최신 minor version delta를 주지 않도록** 서버가 기기 update_engine 버전을 알아야 할 수 있음(full payload는 항상 호환).
- 출처: https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/payload_consumer/delta_performer.cc , https://chromium.googlesource.com/aosp/platform/system/update_engine/+/HEAD/README.md

### 3.6 참조 샘플 앱: SystemUpdaterSample
- 위치: `bootable/recovery/updater_sample`
- 설정 JSON(`UpdateConfig`): `name`, `url`, `ab_install_type`(`NON_STREAMING`|`STREAMING`), `ab_streaming_metadata.property_files[]`(`filename`,`offset`,`size`), `ab_config.force_switch_slot`, `ab_config.verify_payload_metadata`, 인증 헤더.
- `tools/gen_update_config.py` 로 OTA zip에서 config 생성.
- STREAMING: 필요한 엔트리만 다운로드(payload_metadata/payload_properties), payload.bin은 update_engine이 URL+offset으로 직접 스트리밍.
- 출처: https://android.googlesource.com/platform/bootable/recovery/+/refs/heads/main/updater_sample/README.md

### 3.7 재부팅 후 merge, 배터리/네트워크
- Virtual A/B: 재부팅 후 snapuserd가 merge 수행, 중단 시 재개. merge 완료 전에는 다음 업데이트 적용이 제한됨 — `cleanupAppliedPayload()` 가 merge 대기/정리 역할 **(세부 동작 코드 기반 추론)**.
- AVB rollback index는 새 슬롯이 successful 마킹된 후에만 증가 → "부팅 성공" 판단 시점이 곧 **롤백 불가 시점**.
- 배터리/충전/Wi-Fi(비측정 네트워크)/유휴 조건 검사는 update_engine이 아닌 **클라이언트 앱 정책**. 구체 임계값(예: 배터리 %)은 AOSP 공식 문서에 없음 **(미확인)**. `NETWORK_ID` 헤더로 특정 네트워크 바인딩 가능.
- GrapheneOS 사례: 약 6시간마다 메타데이터 확인, 허용된 네트워크에서만 다운로드(https://grapheneos.org/usage).

---

## 4. 보안

### 4.1 서명 키
- 테스트 키(`build/target/product/security`)는 공개 → 프로덕션은 **release-keys** 필수. 키 = `.x509.pem`(인증서) + `.pk8`(개인키). 기본 키: releasekey(testkey 슬롯), platform, shared, media, networkstack (+APEX별 container/payload key).
- OTA 검증 키 위치: 시스템 `/system/etc/security/otacerts.zip`, recovery `/res/keys`. 사이드로드 추가키 `PRODUCT_EXTRA_RECOVERY_KEYS`.
- update_engine payload 검증 인증서 경로 상수 `kUpdateCertificatesPath` 사용, otacerts.zip 기반 `PayloadVerifier::CreateInstanceFromZipPath()` **(코드 기반 추론)**. 레거시 경로 `update-payload-key.pub.pem` 사용 여부는 버전별 차이 **(미확인)**.
- 키 보관: 에어갭/암호화 볼트, 암호화된 pk8, RAM disk 생성 권장. APK 키 로테이션은 APK Signature Scheme v3.
- **OTA 키 로테이션 절차**(구 키로 서명된 전환 빌드에 신 키 인증서를 otacerts에 포함시킨 후 신 키로 전환) — 공식 절차 문서 **(미확인)**.
- 출처: https://source.android.com/docs/core/ota/sign_builds

### 4.2 서명/무결성 체인
1. zip 전체 서명(releasekey) — recovery/sideload 경로 검증.
2. payload metadata 서명 + payload 서명(`CrAU` 내부) — update_engine이 metadata 먼저 검증 후 operation별 SHA-256 해시로 나머지 검증.
3. `FILE_HASH`/`METADATA_HASH` 헤더 — 서버가 전달한 값과 실제 다운로드 비교(전송 계층 변조/CDN 오염 탐지).
4. AVB 2.0 — 부팅 시 vbmeta 서명 + rollback index.
- 출처: https://chromium.googlesource.com/aosp/platform/system/update_engine/+/HEAD/README.md

### 4.3 AVB 2.0 Rollback Protection
- VBMeta마다 rollback index 보유, tamper-evident 저장소의 stored index 이상이어야 신뢰.
- stored index는 **슬롯이 successful로 마킹된 후에만 증가**, 슬롯별 독립.
- SPL 날짜를 rollback index로 쓰는 방식 권장 예시.
- A/B는 부팅 성공 전까지 이전 슬롯 폴백 가능 → rollback protection과 충돌하지 않음.
- 출처: https://android.googlesource.com/platform/external/avb/+/refs/heads/main/README.md , https://source.android.com/docs/core/ota/ab/ab_faqs

### 4.4 다운그레이드/SPL 규칙 정리
| 계층 | 조건 | 결과 |
|---|---|---|
| 패키지 생성 | target timestamp < source | `--downgrade`(wipe 강제) 또는 `--override_timestamp` 없으면 생성 실패 |
| 패키지 생성 | target SPL < source SPL | `--spl_downgrade` 필요 |
| update_engine | build timestamp > `max_timestamp` | 51 PAYLOAD_TIMESTAMP_ERROR |
| update_engine | 잠긴 부트로더 + SPL 하락 | 거부 |
| 부트로더(AVB) | rollback index < stored | 부팅 거부 |

→ **백엔드 설계 결론**: 문제 빌드 롤백은 "이전 빌드 재배포"가 아닌 **수정된 신규 빌드(roll-forward)** 로 해결. 서버는 target의 timestamp/SPL이 source보다 낮은 조합을 배포 불가로 검증해야 한다.

### 4.5 전송 보안
- `AUTHORIZATION` 헤더로 서명 URL/토큰 대신 Bearer 인증 가능. 무결성은 payload 서명으로 보장되므로 TLS는 기밀성/메타데이터 보호 목적. update_engine의 TLS 인증서 pinning 여부 **(미확인)**.

---

## 5. 서버 측 설계

### 5.1 Omaha 프로토콜 (Chrome OS update_engine의 참조 모델)
- Request(XML, protocol 3.0): `request@requestid, sessionid, protocol, updater, updaterversion, installsource, ismachine`; `os@version, platform, sp`; `app@appid, version, from_version, track, from_track, cohort, cohorthint, cohortname, fingerprint, os_build_type, board, hardware_class, delta_okay, lang, requisition`; `updatecheck@targetversionprefix, rollback_allowed, ltstag`; `ping`; `event@eventtype, eventresult, errorcode`.
- Response: `daystart@elapsed_days`; `app/updatecheck@status`(ok/noupdate/error); `urls/url@codebase`; `manifest@version/packages/package@hash_sha256, size, name`; `actions`(postinstall 파라미터 — Chrome OS는 metadata size/signature, delta 여부 등을 여기에 전달, 필드명 **(미확인)**).
- **cohort** 로 클라이언트 그룹핑 → 서버가 응답으로 cohort 변경 가능 → staged rollout 수단.
- Chrome OS 정책: update check scattering(무작위 분산), backoff, P2P(요청은 항상 HTTPS 서버 경유), enterprise staged rollout(% 단계), target version pinning, rollback+powerwash.
- 헤더 상수: `X-Goog-Update-Interactivity`, `X-Goog-Update-AppId`, `X-Goog-Update-Updater`, `X-Goog-SessionId`.
- Android 기기에는 Omaha 클라이언트가 기본 경로가 아니므로, **Omaha는 "요청/응답/이벤트 스키마 설계 레퍼런스"로만 활용** 권장.
- 출처: https://github.com/google/omaha/blob/main/doc/ServerProtocolV3.md , https://pkg.go.dev/chromium.googlesource.com/chromiumos/platform/tast-tests.git/src/chromiumos/tast/remote/bundles/cros/omaha/request , https://support.google.com/chrome/a/answer/3168106?hl=en

### 5.2 기기가 보고해야 할 데이터 (권장 요청 스키마)
AOSP가 표준 요청 형식을 정의하지 않으므로 아래는 metadata 매칭 조건과 Omaha 필드에서 역산한 **설계 제안**이다.

| 필드 | 소스(시스템 프로퍼티 등) | 서버 용도 |
|---|---|---|
| device / product | `ro.product.device` (metadata `pre-device`) | 모델 매칭 |
| build fingerprint | `ro.build.fingerprint` (metadata `pre-build`) | delta source 매칭 (필수) |
| build incremental | `ro.build.version.incremental` | 버전 비교/표시 |
| build timestamp | `ro.build.date.utc` | 다운그레이드 방지 검증 |
| SPL | `ro.build.version.security_patch` | SPL 다운그레이드 방지 |
| SDK level | `ro.build.version.sdk` | OS 업그레이드 대상 판단 |
| 현재 슬롯 | `ro.boot.slot_suffix` | 진단 |
| 업데이트 상태 | UpdateEngine status / 마지막 error code | 텔레메트리 |
| carrier / region / SKU | OEM 프로퍼티 **(표준 없음)** | 타겟팅 |
| 채널 | 앱 설정(stable/beta) | 채널 |
| 기기 식별자(해시) | OEM 정의 | 코호트 버킷팅(안정적 해시) |
| 여유 공간, 배터리, 네트워크 종류 | 앱 수집 | 정책/실패 분석 |
| update_engine 지원 minor version | **(미확인 — 노출 API 확인 필요)** | delta 호환성 |

### 5.3 서버가 반환해야 할 데이터 (권장 응답 스키마)
- `update_available`, `target_version`(표시용), `post_build` fingerprint, `post_timestamp`, `post_spl`
- `type`: full | incremental, `wipe`, `downgrade`(원칙적으로 false)
- `url`(CDN, 서명 URL 또는 AUTHORIZATION 토큰), `size`, `sha256`(zip 전체)
- `payload_offset`, `payload_size` (`ota-streaming-property-files` 의 payload.bin 항목)
- `payload_properties`: FILE_HASH, FILE_SIZE, METADATA_HASH, METADATA_SIZE (→ headerKeyValuePairs)
- `payload_metadata` offset/size (`verifyPayloadMetadata`/`allocateSpace` 선행용)
- 정책: `install_window`, `require_wifi`, `min_battery`, `switch_slot_on_reboot`, `mandatory/deadline`, 다음 체크 간격(backoff/scatter)
- `rollout_id` / `cohort` (이벤트 상관관계)
- 참조 구현: LineageOS Updater 23.2 응답은 `datetime`, `type`, `version`, `files[]{filename, os_patch_level, os_sdk_level, ota_property_files, sha256, size, url}` — **`ota_property_files` 문자열을 그대로 내려주는 방식**이 간결한 레퍼런스.

### 5.4 Delta 선택 매트릭스
- incremental은 `precondition.build`(source fingerprint) 가 정확히 일치해야 설치 가능 → 키는 `(device, source_fingerprint, target_fingerprint)`.
- 전략 예시(설계 제안):
  - 최근 N개 source 빌드(활성 기기 분포 상위) → target delta 사전 생성
  - 매트릭스에 없으면 full 폴백 (GrapheneOS: `DEVICE-incremental-OLD-NEW.zip` 시도 후 `DEVICE-ota_update-NEW.zip` 폴백)
  - multi-hop(구→중간→신) 연쇄 업데이트 vs 직접 delta 트레이드오프: hop마다 재부팅·merge 필요
- 활성 기기의 source 빌드 분포 텔레메트리가 **delta 생성 우선순위 결정 입력**이 된다.
- OS 메이저 업그레이드 delta 크기, full 대비 비율은 공식 수치 없음 **(미확인)**. 참고 수치: "A full Pixel system update writes about 2.3GiB"(A/B FAQ).

### 5.5 Staged Rollout (단계적 배포)
- 공식 AOSP 문서에 서버 롤아웃 정책 규정 없음. 확인된 사례:
  - Pixel: 업데이트가 단계적으로(carrier·기기 의존) 수 주에 걸쳐 배포(https://support.google.com/pixelphone/answer/4457705).
  - Chrome OS 엔터프라이즈: % 기반 staged rollout, 일 단위 scattering.
  - Omaha: cohort 기반 채널 이동.
  - GrapheneOS: testing → beta → stable 채널 승격.
- 설계 제안(업계 일반 패턴, 특정 OEM 수치 **(미확인)**):
  - 안정적 해시(`hash(device_id + rollout_id) mod 10000`)로 % 버킷 — 비율 증가 시 기존 대상 유지
  - 코호트: 내부 → 베타 → 1% → 5% → 25% → 100% 등 (비율은 조직 결정)
  - 자동 중단(halt) 신호: 설치 에러율(에러 코드별), `UPDATED_BUT_NOT_ACTIVE`(52)·슬롯 폴백(부팅 실패 후 이전 빌드 fingerprint로 재보고), 부팅 후 successful 마킹 비율, 크래시/ANR 증가, merge 실패, `NOT_ENOUGH_SPACE` 급증
  - 부팅 실패 탐지는 **업데이트 후 첫 체크인에서 fingerprint가 post-build인지 pre-build인지** 비교하는 방식이 가장 단순(설계 제안).
  - Halt는 "신규 할당 중단"만 가능 — 이미 슬롯 전환·successful 마킹된 기기는 되돌릴 수 없음(4.4 참조).
  - `SWITCH_SLOT_ON_REBOOT=false` 로 선적용 후 서버 신호 시 `setShouldSwitchSlotOnReboot()` 로 전환하는 2단계 활성화도 가능(설계 제안).

### 5.6 CDN/대역폭
- 스트리밍: update_engine이 `url` + `offset/size` 로 zip 내부를 읽음 → libcurl 기반 fetcher 사용. **HTTP Range 지원 필수**(URL의 특정 바이트 구간을 읽고 재개하려면 필요 — 코드 기반 추론, 공식 문서 명시 **(미확인)**).
- CDN 캐시 키는 URL만 사용(서명 쿼리/Authorization 헤더가 캐시 분할하지 않도록), 객체는 불변(immutable) 파일명(빌드 ID/해시 포함).
- 재시도: update_engine 기본 20회 재시도 + resume(payload_id) → 동일 URL/해시 유지.
- 대역폭 관리: incremental 우선, Wi-Fi 전용 정책, 체크 scattering, 코호트 페이싱, 피크 시간 회피. GrapheneOS는 정적 파일 서버만으로 운영.
- 출처: https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/aosp/update_attempter_android.cc , https://grapheneos.org/build

### 5.7 오픈소스 서버/포맷 레퍼런스
| 프로젝트 | 포맷 |
|---|---|
| LineageOS Updater | `GET https://download.lineageos.org/api/v2/devices/{device}/builds` (placeholder `{device}`, `{type}`, `{incr}`), JSON 배열: `datetime`, `type`, `version`, `files[]{filename, os_patch_level, os_sdk_level, ota_property_files, sha256, size, url}`. 구버전: `{"response":[{datetime, filename, id, romtype, size, url, version}]}` |
| LineageOTA (커뮤니티) | LineageOS Updater용 REST 서버 구현 — https://github.com/julianxhokaxhiu/LineageOTA |
| GrapheneOS | 정적 파일: `DEVICE-stable`/`DEVICE-beta`/`DEVICE-testing` 채널 메타데이터, `DEVICE-ota_update-BUILD.zip`, `DEVICE-incremental-OLD-NEW.zip`. 메타데이터 파일 내부 필드 순서 **(미확인)** |
| Omaha | Google 오픈소스 클라이언트/프로토콜(서버는 비공개). 커뮤니티 서버 구현 존재 여부 **(미확인)** |
| AOSP SystemUpdaterSample | 서버 없음, `gen_update_config.py` 로 config JSON 생성 |

---

## 6. Google Play 시스템 업데이트(Mainline) vs 전체 OS OTA

| 구분 | Full OS OTA | Mainline (Google Play system update) |
|---|---|---|
| 도입 | — | Android 10 |
| 대상 | 모든 파티션(system/vendor/boot 등), OS 메이저 버전·SDK 변경 | 모듈화된 시스템 컴포넌트(APEX: ART(12+), Bluetooth(13+), DNS Resolver/Media/Tzdata(10+), Wi-Fi/Tethering(11+) 등; APK: DocumentsUI, PermissionController 등) |
| 전달 | OEM OTA 서버 → update_engine | Google Play 시스템 업데이트 또는 파트너 OTA |
| 설치 | A/B/VAB 슬롯, 재부팅 | PackageManager → apexd staged 설치, 재부팅 필요, `/data` 에 저장 후 `/apex/<name>@<version>` 마운트 |
| 원자성 | 슬롯 단위 | 필요한 모듈 전부 or 전무(train) |
| 서명 | releasekey + AVB | APEX payload key + container key(APK Sig v3) |
| API | 새 API/SDK 레벨 도입 | 새 API 도입 불가, stable API/AIDL만 |
| 롤백 | 사실상 불가(부팅 성공 후) | 모듈 롤백 메커니즘 존재(세부 **(미확인)**) |

- Android 11 이하에 대한 Mainline 지원은 2025년 4분기 종료(공식 문서 노트).
- OS OTA 패키지에도 `apex_info.pb` 가 포함되어 update_engine이 압축 APEX 해제 공간을 사전 할당.
- 백엔드 영향: OS 버전 업그레이드 서버는 **Mainline 버전을 배포 대상으로 관리하지 않지만**, 기기 텔레메트리에 모듈 버전을 포함하면 이슈 분석에 유용(설계 제안).
- 출처: https://source.android.com/docs/core/ota/modular-system , https://source.android.com/docs/core/ota/apex

---

## 7. 백엔드 설계 시사점 체크리스트

1. **Artifact 수집 파이프라인**: OTA zip 업로드 시 `metadata.pb`, `payload_properties.txt`, `ota-streaming-property-files` 파싱 → `ota_package` 테이블(device, type, pre_builds[], post_build, post_timestamp, post_spl, sdk, wipe, downgrade, spl_downgrade, url, size, sha256, payload_offset/size, file_hash, metadata_hash/size).
2. **매칭 규칙**: device 일치 ∧ (full ∨ source fingerprint ∈ pre_builds) ∧ post_timestamp > 현재 timestamp ∧ post_spl ≥ 현재 spl ∧ 롤아웃 대상 포함.
3. **API 계약**: 응답에 applyPayload 직결 필드(url, offset, size, headers[]) 포함.
4. **오리진/CDN**: Range 지원, immutable 객체, 서명 URL 또는 AUTHORIZATION 토큰.
5. **텔레메트리 이벤트**: check, download_start, status 전이, error_code(native 코드 + 플래그), UPDATED_NEED_REBOOT, 재부팅 후 fingerprint 보고(성공/폴백 판정), merge 완료.
6. **롤아웃 제어**: 안정적 해시 버킷, 코호트, 자동 halt 임계값, roll-forward 전제.
7. **키 관리**: releasekey/AVB/APEX 키는 서버와 분리(HSM/`--payload_signer`), 서버는 서명된 산출물만 배포.

---

## 출처

### source.android.com
- https://source.android.com/docs/core/ota/ab
- https://source.android.com/docs/core/ota/ab/ab_implement
- https://source.android.com/docs/core/ota/ab/ab_faqs
- https://source.android.com/docs/core/ota/nonab
- https://source.android.com/docs/core/ota/virtual_ab
- https://source.android.com/docs/core/ota/virtual_ab/implement
- https://source.android.com/docs/core/ota/virtual_ab/implement-patches
- https://source.android.com/docs/core/ota/dynamic_partitions
- https://source.android.com/docs/core/ota/dynamic_partitions/implement
- https://source.android.com/docs/core/ota/tools
- https://source.android.com/docs/core/ota/reduce_size
- https://source.android.com/docs/core/ota/sign_builds
- https://source.android.com/docs/core/ota/modular-system
- https://source.android.com/docs/core/ota/apex
- https://source.android.com/docs/security/features/verifiedboot/avb

### AOSP 소스 (googlesource)
- https://android.googlesource.com/platform/build/+/refs/heads/main/tools/releasetools/ota_from_target_files.py
- https://android.googlesource.com/platform/build/+/refs/heads/main/tools/releasetools/ota_utils.py
- https://android.googlesource.com/platform/build/+/refs/heads/main/tools/releasetools/ota_metadata.proto
- https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/os/UpdateEngine.java
- https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/common/constants.h
- https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/common/error_code.h
- https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/aosp/update_attempter_android.cc
- https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/payload_consumer/delta_performer.cc
- https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/update_metadata.proto
- https://android.googlesource.com/platform/system/update_engine/+/refs/heads/main/README.md
- https://chromium.googlesource.com/aosp/platform/system/update_engine/+/HEAD/README.md
- https://android.googlesource.com/platform/system/core/+/refs/heads/main/fs_mgr/libsnapshot/include/libsnapshot/cow_format.h
- https://android.googlesource.com/platform/bootable/recovery/+/refs/heads/main/updater_sample/README.md
- https://android.googlesource.com/platform/external/avb/+/refs/heads/main/README.md

### Omaha / Chrome OS
- https://github.com/google/omaha/blob/main/doc/ServerProtocolV3.md
- https://pkg.go.dev/chromium.googlesource.com/chromiumos/platform/tast-tests.git/src/chromiumos/tast/remote/bundles/cros/omaha/request
- https://support.google.com/chrome/a/answer/3168106?hl=en

### 오픈소스 업데이터 / 기타
- https://github.com/LineageOS/android_packages_apps_Updater/blob/lineage-23.2/README.md
- https://github.com/julianxhokaxhiu/LineageOTA
- https://github.com/GrapheneOS/platform_packages_apps_Updater
- https://github.com/GrapheneOS/releases.grapheneos.org
- https://grapheneos.org/build
- https://grapheneos.org/usage
- https://support.google.com/pixelphone/answer/4457705?hl=en
- https://www.esper.io/blog/android-13-virtual-ab-requirement (2차 출처)
- https://lpc.events/event/16/contributions/1331/attachments/951/1867/LPC2022%20-%20io_uring%20in%20Android%20OTA.pdf
