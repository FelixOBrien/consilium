-- Consilium schema. Specification: docs/models/ (every stored model). pragma: allowlist secret
-- search_hit is an API shape and has no table.
-- Portable Postgres + pgvector. No Lakebase Search syntax and no superuser settings.
-- Embedding spaces stay separate: halfvec(768) is conchz, vector(384) is report.
-- Non-vector indexes live here. HNSW and GIN are applied later by 0002_indexes.sql
-- so a bulk load can insert rows before building those indexes.

create extension if not exists vector;

-- Specialty values shared by path_case.specialty and the columns copied from it:
-- breast, thorax, colorectal, gastrointestinal, hematologic, skin.

create table pathologist (
    id text primary key,
    name text not null,
    role_title text not null,
    primary_specialty text not null,
    secondary_specialties text[] not null default '{}',
    is_demo_user boolean not null,
    is_synthetic boolean not null,
    created_at timestamptz not null default now(),
    constraint pathologist_primary_specialty_check check (
        primary_specialty in (
            'breast', 'thorax', 'colorectal', 'gastrointestinal', 'hematologic', 'skin'
        )
    ),
    constraint pathologist_secondary_specialties_check check (
        secondary_specialties <@ array[
            'breast', 'thorax', 'colorectal', 'gastrointestinal', 'hematologic', 'skin'
        ]::text[]
    ),
    constraint pathologist_is_synthetic_check check (is_synthetic)
);

-- At most one demo identity. The seed is what inserts that row.
create unique index pathologist_one_demo_user
    on pathologist (is_demo_user)
    where is_demo_user;

create table patient (
    id text primary key,
    display_label text not null,
    sex text,
    birth_year integer,
    is_synthetic_linkage boolean not null,
    created_at timestamptz not null default now(),
    constraint patient_sex_check check (sex is null or sex in ('F', 'M'))
);

create unique index patient_display_label_lower
    on patient (lower(display_label));

create table concept (
    id text primary key,
    label text not null,
    prompt text not null,
    negative_prompt text,
    specialty text,
    ordinal integer not null,
    embedding halfvec(768),
    negative_embedding halfvec(768),
    created_at timestamptz not null default now(),
    constraint concept_specialty_check check (
        specialty is null or specialty in (
            'breast', 'thorax', 'colorectal', 'gastrointestinal', 'hematologic', 'skin'
        )
    )
);

create table path_case (
    id text primary key,
    patient_id text not null references patient (id),
    specimen_label text,
    source_dataset text not null,
    source_case_id text not null,
    specialty text not null,
    patient_age integer,
    patient_sex text,
    primary_diagnosis text,
    morphology text,
    icd10 text,
    status text not null,
    assigned_to text not null references pathologist (id),
    accessioned_at timestamptz not null,
    is_held_out boolean not null,
    cohort_tier text not null,
    created_at timestamptz not null default now(),
    constraint path_case_specialty_check check (
        specialty in (
            'breast', 'thorax', 'colorectal', 'gastrointestinal', 'hematologic', 'skin'
        )
    ),
    constraint path_case_patient_sex_check check (
        patient_sex is null or patient_sex in ('F', 'M')
    ),
    constraint path_case_status_check check (status in ('open', 'signed_out')),
    constraint path_case_cohort_tier_check check (
        cohort_tier in ('smoke', 'demo', 'stretch')
    ),
    constraint path_case_status_matches_held_out check (
        (status = 'open') = is_held_out
    ),
    constraint path_case_source_unique unique (source_dataset, source_case_id)
);

create index path_case_patient_accessioned
    on path_case (patient_id, accessioned_at desc);

create index path_case_status_assigned_accessioned
    on path_case (status, assigned_to, accessioned_at desc);

create index path_case_specialty_accessioned
    on path_case (specialty, accessioned_at desc);

create index path_case_icd10_prefix
    on path_case (icd10 text_pattern_ops);

create table slide (
    id text primary key,
    case_id text not null references path_case (id),
    ordinal integer not null,
    stain text not null,
    magnification real not null,
    mpp real not null,
    width integer not null,
    height integer not null,
    patch_size integer not null,
    patch_count integer not null,
    storage_key text not null,
    thumb_pack_key text,
    source_path text not null,
    embedding halfvec(768),
    status text not null,
    created_at timestamptz not null default now(),
    constraint slide_status_check check (
        status in ('pending', 'processing', 'ready', 'failed')
    ),
    constraint slide_case_ordinal_unique unique (case_id, ordinal),
    constraint slide_ready_assets_check check (
        (
            status = 'ready'
            and embedding is not null
            and thumb_pack_key is not null
        )
        or (
            status <> 'ready'
            and embedding is null
            and thumb_pack_key is null
        )
    )
);

create table report (
    id text primary key,
    case_id text not null unique references path_case (id),
    author_id text not null references pathologist (id),
    status text not null,
    body text not null,
    clinical_history text,
    gross_description text,
    microscopic_description text,
    conclusion text,
    additional_info text,
    icd10 text,
    signed_at timestamptz,
    search_tsv tsvector generated always as (
        setweight(to_tsvector('english', coalesce(conclusion, '')), 'A')
        || setweight(to_tsvector('english', coalesce(microscopic_description, '')), 'B')
        || setweight(to_tsvector('english', coalesce(additional_info, '')), 'B')
        || setweight(to_tsvector('english', coalesce(gross_description, '')), 'C')
        || setweight(to_tsvector('english', coalesce(clinical_history, '')), 'C')
        || setweight(to_tsvector('english', coalesce(body, '')), 'C')
    ) stored not null,
    created_at timestamptz not null default now(),
    constraint report_status_check check (status in ('signed', 'withheld', 'draft')),
    constraint report_body_not_empty check (char_length(body) > 0),
    constraint report_signed_at_only_when_signed check (
        signed_at is null or status = 'signed'
    )
);

create index report_author_id on report (author_id);

create index report_status on report (status);

create table patch (
    id bigint generated always as identity primary key,
    slide_id text not null references slide (id) on delete cascade,
    case_id text not null references path_case (id),
    patient_id text not null references patient (id),
    specialty text not null,
    x integer not null,
    y integer not null,
    size integer not null,
    embedding halfvec(768) not null,
    in_corpus boolean not null,
    thumb_offset bigint not null,
    thumb_length integer not null,
    created_at timestamptz not null default now(),
    constraint patch_specialty_check check (
        specialty in (
            'breast', 'thorax', 'colorectal', 'gastrointestinal', 'hematologic', 'skin'
        )
    ),
    constraint patch_slide_position_unique unique (slide_id, x, y)
);

create index patch_case_id on patch (case_id);

create index patch_patient_id on patch (patient_id);

create table report_chunk (
    id bigint generated always as identity primary key,
    report_id text not null references report (id) on delete cascade,
    case_id text not null references path_case (id),
    patient_id text not null references patient (id),
    specialty text not null,
    section text not null,
    ordinal integer not null,
    text text not null,
    embedding vector(384) not null,
    in_corpus boolean not null,
    created_at timestamptz not null default now(),
    constraint report_chunk_specialty_check check (
        specialty in (
            'breast', 'thorax', 'colorectal', 'gastrointestinal', 'hematologic', 'skin'
        )
    ),
    constraint report_chunk_section_check check (
        section in (
            'clinical_history',
            'gross_description',
            'microscopic_description',
            'conclusion',
            'additional_info',
            'body'
        )
    ),
    constraint report_chunk_report_ordinal_unique unique (report_id, ordinal)
);

create index report_chunk_patient_id on report_chunk (patient_id);

create table annotation (
    id uuid primary key default gen_random_uuid(),
    slide_id text not null references slide (id) on delete cascade,
    case_id text not null references path_case (id),
    author_id text not null references pathologist (id),
    kind text not null,
    geometry jsonb not null,
    label text not null,
    note text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint annotation_kind_check check (kind in ('rect', 'point')),
    constraint annotation_label_length check (char_length(label) between 1 and 80),
    constraint annotation_geometry_shape check (
        jsonb_typeof(geometry) = 'object'
        and (
            (kind = 'point' and geometry ? 'x' and geometry ? 'y')
            or (
                kind = 'rect'
                and geometry ? 'x'
                and geometry ? 'y'
                and geometry ? 'width'
                and geometry ? 'height'
            )
        )
    )
);

create index annotation_slide_created
    on annotation (slide_id, created_at);

create table consult_thread (
    id uuid primary key default gen_random_uuid(),
    case_id text not null references path_case (id),
    user_id text not null references pathologist (id),
    title text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index consult_thread_case_user_updated
    on consult_thread (case_id, user_id, updated_at desc);

create table consult_message (
    id uuid primary key default gen_random_uuid(),
    thread_id uuid not null references consult_thread (id) on delete cascade,
    role text not null,
    content text not null,
    attachments jsonb,
    citations jsonb,
    ranking jsonb,
    tool_trace jsonb,
    model text,
    input_tokens integer,
    output_tokens integer,
    status text not null,
    created_at timestamptz not null default now(),
    constraint consult_message_role_check check (role in ('user', 'assistant')),
    constraint consult_message_status_check check (
        status in ('complete', 'streaming', 'error')
    )
);

create index consult_message_thread_created
    on consult_message (thread_id, created_at);

create table ingestion_job (
    id uuid primary key default gen_random_uuid(),
    dataset text not null,
    slide_path text not null,
    case_id text,
    slide_id text,
    requested_by text references pathologist (id),
    status text not null,
    stage text,
    stage_history jsonb not null default '[]'::jsonb,
    counts jsonb,
    error text,
    attempts integer not null default 0,
    worker_id text,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    constraint ingestion_job_status_check check (
        status in ('queued', 'running', 'done', 'failed')
    ),
    constraint ingestion_job_stage_check check (
        stage is null or stage in (
            'download', 'segment', 'embed', 'project', 'thumbnails', 'reports', 'load', 'index'
        )
    )
);

create index ingestion_job_status_created
    on ingestion_job (status, created_at);

create unique index ingestion_job_active_slide
    on ingestion_job (dataset, slide_path)
    where status in ('queued', 'running');
