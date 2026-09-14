# OTA metadata 픽스처 (공개 패키지에서 추출, 2026-09-14)

| 파일 | 원본 패키지 (zip 엔트리 `META-INF/com/android/metadata[.pb]`) |
|---|---|
| `lynx-cp2a.260705.006.metadata(.pb)` | Google Pixel 7a full OTA `https://dl.google.com/dl/android/aosp/lynx-ota-cp2a.260705.006-f4d6d546.zip` (Android 17) |
| `tokay-incremental-2026090700-2026091000.metadata.pb` | GrapheneOS(AOSP 기반) Pixel 9 incremental OTA `https://releases.grapheneos.org/tokay-incremental-2026090700-2026091000.zip` (Android 17) |

패키지 전체가 아니라 HTTP Range 로 metadata 엔트리만 읽어 저장했다. GrapheneOS 패키지는 Google 이 공개하지 않는
AOSP A/B **incremental** 형식의 실파일 표본으로만 사용한다.
