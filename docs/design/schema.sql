-- android-os backend 스키마 초안 (PostgreSQL 15+)
-- 03-data-model.md 와 동기화 유지

-- ------------------------------------------------------------------ Readiness
CREATE TABLE platform (
    id                   BIGSERIAL PRIMARY KEY,
    soc                  TEXT NOT NULL,
    name                 TEXT NOT NULL UNIQUE,
    android_version      TEXT NOT NULL,              -- '16', '16-QPR2'
    first_api_level      INT  NOT NULL,
    board_api_level      INT,                        -- YYYYMM
    board_api_frozen     BOOLEAN NOT NULL DEFAULT FALSE,
    kernel_branch        TEXT NOT NULL,              -- 'android16-6.12'
    fcm_target_level     TEXT,                       -- '202504'
    page_size_kb         INT  NOT NULL DEFAULT 4 CHECK (page_size_kb IN (4, 16)),
    supports_16kb        BOOLEAN NOT NULL DEFAULT FALSE,
    uses_vndk            BOOLEAN NOT NULL DEFAULT FALSE,
    uses_ion             BOOLEAN NOT NULL DEFAULT FALSE,
    sepolicy_memfd_ready BOOLEAN NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE platform_hal (
    platform_id BIGINT NOT NULL REFERENCES platform(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    transport   TEXT NOT NULL CHECK (transport IN ('hidl', 'aidl')),
    version     TEXT NOT NULL,
    PRIMARY KEY (platform_id, name, transport, version)
);

CREATE TABLE device_model (
    id             BIGSERIAL PRIMARY KEY,
    platform_id    BIGINT NOT NULL REFERENCES platform(id),
    device         TEXT NOT NULL UNIQUE,             -- ro.product.device
    marketing_name TEXT,
    skus           TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE readiness_run (
    id             BIGSERIAL PRIMARY KEY,
    platform_id    BIGINT NOT NULL REFERENCES platform(id),
    target_release TEXT NOT NULL,
    kb_version     TEXT NOT NULL,
    summary        JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE finding (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES readiness_run(id) ON DELETE CASCADE,
    rule_id     TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('blocker', 'warning', 'info')),
    title       TEXT NOT NULL,
    detail      TEXT NOT NULL,
    evidence    JSONB NOT NULL DEFAULT '{}',
    source_urls TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE work_item (
    id           BIGSERIAL PRIMARY KEY,
    finding_id   BIGINT UNIQUE REFERENCES finding(id),
    status       TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done', 'waived')),
    owner        TEXT,
    waive_reason TEXT,
    external_ref TEXT,
    CHECK (status <> 'waived' OR waive_reason IS NOT NULL)
);

-- ------------------------------------------------------------------ OTA
CREATE TABLE build (
    id              BIGSERIAL PRIMARY KEY,
    device_model_id BIGINT NOT NULL REFERENCES device_model(id),
    fingerprint     TEXT NOT NULL UNIQUE,
    incremental     TEXT NOT NULL,
    timestamp_utc   BIGINT NOT NULL,                 -- ro.build.date.utc
    spl             DATE NOT NULL,
    sdk_level       INT NOT NULL,
    android_release TEXT NOT NULL
);

CREATE TABLE ota_package (
    id                       BIGSERIAL PRIMARY KEY,
    target_build_id          BIGINT NOT NULL REFERENCES build(id),
    type                     TEXT NOT NULL CHECK (type IN ('full', 'incremental')),
    pre_device               TEXT[] NOT NULL,
    pre_builds               TEXT[] NOT NULL DEFAULT '{}',
    post_timestamp           BIGINT NOT NULL,
    post_spl                 DATE NOT NULL,
    post_sdk_level           INT,
    wipe                     BOOLEAN NOT NULL,
    downgrade                BOOLEAN NOT NULL,
    spl_downgrade            BOOLEAN NOT NULL,
    object_key               TEXT NOT NULL UNIQUE,
    url                      TEXT NOT NULL,
    file_size                BIGINT NOT NULL,
    sha256                   CHAR(64) NOT NULL,
    payload_offset           BIGINT NOT NULL,
    payload_size             BIGINT NOT NULL,
    payload_properties       JSONB NOT NULL,
    streaming_property_files TEXT NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'ready', 'rejected', 'retired')),
    reject_reasons           TEXT[] NOT NULL DEFAULT '{}',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (type = 'full' OR cardinality(pre_builds) >= 1)
);
CREATE INDEX ota_package_pre_builds_gin ON ota_package USING GIN (pre_builds);
CREATE INDEX ota_package_target ON ota_package (target_build_id, type) WHERE status = 'ready';

-- ready 패키지의 불변 필드 변경 차단 (NF-02)
CREATE FUNCTION ota_package_immutable() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'ready' AND (NEW.object_key, NEW.sha256, NEW.payload_properties, NEW.payload_offset, NEW.payload_size)
        IS DISTINCT FROM (OLD.object_key, OLD.sha256, OLD.payload_properties, OLD.payload_offset, OLD.payload_size) THEN
        RAISE EXCEPTION 'ota_package % is ready; payload fields are immutable', OLD.id;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER ota_package_immutable BEFORE UPDATE ON ota_package
    FOR EACH ROW EXECUTE FUNCTION ota_package_immutable();

CREATE TABLE rollout (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    target_build_id BIGINT NOT NULL REFERENCES build(id),
    channel         TEXT NOT NULL CHECK (channel IN ('testing', 'beta', 'stable')),
    filters         JSONB NOT NULL DEFAULT '{}',
    state           TEXT NOT NULL DEFAULT 'draft'
                    CHECK (state IN ('draft', 'active', 'paused', 'halted', 'completed')),
    current_percent NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (current_percent BETWEEN 0 AND 100),
    halt_rules      JSONB NOT NULL DEFAULT '{}',
    halt_mode       TEXT NOT NULL DEFAULT 'stop_new' CHECK (halt_mode IN ('stop_new', 'stop_all_pending')),
    policy          JSONB NOT NULL DEFAULT '{}',
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rollout_stage (
    rollout_id     BIGINT NOT NULL REFERENCES rollout(id) ON DELETE CASCADE,
    seq            INT NOT NULL,
    percent        NUMERIC(5, 2) NOT NULL,
    min_soak_hours INT NOT NULL DEFAULT 24,
    promoted_at    TIMESTAMPTZ,
    promoted_by    TEXT,
    PRIMARY KEY (rollout_id, seq)
);

CREATE TABLE assignment (
    id                 BIGSERIAL PRIMARY KEY,
    rollout_id         BIGINT NOT NULL REFERENCES rollout(id),
    device_hash        CHAR(64) NOT NULL,
    package_id         BIGINT NOT NULL REFERENCES ota_package(id),
    source_fingerprint TEXT NOT NULL,
    state              TEXT NOT NULL DEFAULT 'offered'
                       CHECK (state IN ('offered', 'downloading', 'installed_pending_reboot',
                                        'boot_success', 'boot_fallback', 'failed')),
    last_error_code    BIGINT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rollout_id, device_hash)
);

CREATE TABLE device_event (
    id              BIGSERIAL,
    assignment_id   BIGINT,
    device_hash     CHAR(64) NOT NULL,
    type            TEXT NOT NULL,
    update_status   INT,
    error_code_raw  BIGINT,
    error_code_base INT,
    error_flags     TEXT[] NOT NULL DEFAULT '{}',
    fingerprint     TEXT,
    occurred_at     TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload         JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (id, received_at)
) PARTITION BY RANGE (received_at);

CREATE TABLE rollout_metrics_snapshot (
    rollout_id     BIGINT NOT NULL REFERENCES rollout(id),
    window_end     TIMESTAMPTZ NOT NULL,
    offered        INT NOT NULL,
    installing     INT NOT NULL,
    installed      INT NOT NULL,
    boot_success   INT NOT NULL,
    boot_fallback  INT NOT NULL,
    errors_by_code JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (rollout_id, window_end)
);

CREATE TABLE audit_log (
    id        BIGSERIAL PRIMARY KEY,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL,
    entity_id BIGINT,
    before    JSONB,
    after     JSONB,
    at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
