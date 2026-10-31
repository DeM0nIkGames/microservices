CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    login VARCHAR(128) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT users_role_check CHECK (role IN ('admin', 'user'))
);


CREATE OR REPLACE FUNCTION dataset_train_percent_is_valid(payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT CASE
        WHEN jsonb_typeof(payload) <> 'object' THEN FALSE
        ELSE
            EXISTS (
                SELECT 1
                FROM jsonb_object_keys(payload)
            )
            AND NOT EXISTS (
                SELECT 1
                FROM jsonb_each(payload) AS item(class_id, percent)
                WHERE CASE
                    WHEN class_id !~ '^[0-9]+$' THEN TRUE
                    WHEN jsonb_typeof(percent) <> 'number' THEN TRUE
                    ELSE (percent #>> '{}')::NUMERIC < 0
                      OR (percent #>> '{}')::NUMERIC > 1
                END
            )
    END;
$$;


CREATE OR REPLACE FUNCTION dataset_class_labels_are_valid(payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT CASE
        WHEN jsonb_typeof(payload) <> 'object' THEN FALSE
        ELSE
            EXISTS (
                SELECT 1
                FROM jsonb_object_keys(payload)
            )
            AND NOT EXISTS (
                SELECT 1
                FROM jsonb_each(payload) AS item(class_id, label)
                WHERE class_id !~ '^[0-9]+$'
                   OR jsonb_typeof(label) <> 'string'
                   OR BTRIM(label #>> '{}') = ''
            )
    END;
$$;


CREATE OR REPLACE FUNCTION dataset_class_counts_are_valid(payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT CASE
        WHEN jsonb_typeof(payload) <> 'object' THEN FALSE
        ELSE
            EXISTS (
                SELECT 1
                FROM jsonb_object_keys(payload)
            )
            AND NOT EXISTS (
                SELECT 1
                FROM jsonb_each(payload) AS item(class_id, item_count)
                WHERE CASE
                    WHEN class_id !~ '^[0-9]+$' THEN TRUE
                    WHEN jsonb_typeof(item_count) <> 'number' THEN TRUE
                    ELSE (item_count #>> '{}')::NUMERIC <= 0
                      OR (item_count #>> '{}')::NUMERIC
                         <> TRUNC((item_count #>> '{}')::NUMERIC)
                END
            )
    END;
$$;


CREATE OR REPLACE FUNCTION jsonb_objects_have_same_keys(
    left_object JSONB,
    right_object JSONB
)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT CASE
        WHEN jsonb_typeof(left_object) <> 'object' THEN FALSE
        WHEN jsonb_typeof(right_object) <> 'object' THEN FALSE
        ELSE
            NOT EXISTS (
                (SELECT key
                 FROM jsonb_object_keys(left_object) AS left_keys(key))
                EXCEPT
                (SELECT key
                 FROM jsonb_object_keys(right_object) AS right_keys(key))
            )
            AND NOT EXISTS (
                (SELECT key
                 FROM jsonb_object_keys(right_object) AS right_keys(key))
                EXCEPT
                (SELECT key
                 FROM jsonb_object_keys(left_object) AS left_keys(key))
            )
    END;
$$;


CREATE OR REPLACE FUNCTION run_split_config_is_valid(payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT CASE
        WHEN jsonb_typeof(payload) <> 'object' THEN FALSE
        WHEN NOT payload ? 'train_percent' THEN FALSE
        ELSE dataset_train_percent_is_valid(payload -> 'train_percent')
    END;
$$;


CREATE TABLE IF NOT EXISTS datasets (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    manifest_path TEXT NOT NULL,
    train_percent JSONB NOT NULL,
    class_labels JSONB NOT NULL,
    class_counts JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT datasets_manifest_path_not_blank CHECK (
        BTRIM(manifest_path) <> ''
    ),
    CONSTRAINT datasets_train_percent_check CHECK (
        dataset_train_percent_is_valid(train_percent)
    ),
    CONSTRAINT datasets_class_labels_check CHECK (
        dataset_class_labels_are_valid(class_labels)
    ),
    CONSTRAINT datasets_class_counts_check CHECK (
        dataset_class_counts_are_valid(class_counts)
    ),
    CONSTRAINT datasets_train_labels_keys_check CHECK (
        jsonb_objects_have_same_keys(train_percent, class_labels)
    ),
    CONSTRAINT datasets_labels_counts_keys_check CHECK (
        jsonb_objects_have_same_keys(class_labels, class_counts)
    )
);

CREATE INDEX IF NOT EXISTS datasets_user_id_idx
    ON datasets(user_id);

CREATE INDEX IF NOT EXISTS datasets_created_at_idx
    ON datasets(created_at DESC);


CREATE TABLE IF NOT EXISTS models (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(64) NOT NULL,
    import_url TEXT NOT NULL,

    status VARCHAR(32) NOT NULL DEFAULT 'pending_validation',
    metadata JSONB,
    error_message TEXT,

    validation_worker_id TEXT,
    validation_started_at TIMESTAMPTZ,
    validated_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT models_name_not_blank CHECK (BTRIM(name) <> ''),
    CONSTRAINT models_version_not_blank CHECK (BTRIM(version) <> ''),
    CONSTRAINT models_import_url_not_blank CHECK (BTRIM(import_url) <> ''),
    CONSTRAINT models_status_check CHECK (
        status IN (
            'pending_validation',
            'validating',
            'validated',
            'failed',
            'disabled'
        )
    ),
    CONSTRAINT models_metadata_object_check CHECK (
        metadata IS NULL OR jsonb_typeof(metadata) = 'object'
    ),
    CONSTRAINT models_name_version_unique UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS models_user_id_idx
    ON models(user_id);

CREATE INDEX IF NOT EXISTS models_created_at_idx
    ON models(created_at DESC);

CREATE INDEX IF NOT EXISTS models_validation_queue_idx
    ON models(created_at, id)
    WHERE status = 'pending_validation';


CREATE TABLE IF NOT EXISTS model_runs (
    id BIGSERIAL PRIMARY KEY,
    model_id BIGINT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    dataset_id BIGINT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    seed BIGINT NOT NULL DEFAULT (
        FLOOR(RANDOM() * 9223372036854775807)::BIGINT
    ),
    hyperparameters JSONB NOT NULL DEFAULT '{}'::JSONB,
    split_config JSONB NOT NULL,

    progress JSONB NOT NULL DEFAULT (
        '{"phase":"queued","percent":0.0,"last_message":"Запуск ожидает выполнения"}'::JSONB
    ),
    metrics JSONB NOT NULL DEFAULT '{}'::JSONB,
    results_path TEXT,

    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    error_message TEXT,
    worker_id TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,

    CONSTRAINT model_runs_status_check CHECK (
        status IN ('queued', 'running', 'completed', 'failed', 'cancelled')
    ),
    CONSTRAINT model_runs_hyperparameters_object_check CHECK (
        jsonb_typeof(hyperparameters) = 'object'
    ),
    CONSTRAINT model_runs_split_config_check CHECK (
        run_split_config_is_valid(split_config)
    ),
    CONSTRAINT model_runs_progress_object_check CHECK (
        jsonb_typeof(progress) = 'object'
    ),
    CONSTRAINT model_runs_metrics_object_check CHECK (
        jsonb_typeof(metrics) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS model_runs_model_id_created_at_idx
    ON model_runs(model_id, created_at DESC);

CREATE INDEX IF NOT EXISTS model_runs_dataset_id_idx
    ON model_runs(dataset_id);

CREATE INDEX IF NOT EXISTS model_runs_user_id_idx
    ON model_runs(user_id);

CREATE INDEX IF NOT EXISTS model_runs_status_idx
    ON model_runs(status);

CREATE INDEX IF NOT EXISTS model_runs_queue_idx
    ON model_runs(created_at, id)
    WHERE status = 'queued';


INSERT INTO users (login, password_hash, role)
VALUES ('admin',
        'pbkdf2:sha256:1000000$aB3dE5fG7hJ9kL2m$3c45e7311f90ecd0c3b013cc065ee9bd0dce6aa98d1f0998053e8f6733434a41', 
        'admin')
ON CONFLICT (login) DO NOTHING;
