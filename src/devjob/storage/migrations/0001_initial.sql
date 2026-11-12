CREATE TABLE profile_versions (
    version INTEGER PRIMARY KEY,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE resume_imports (
    file_hash TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    text_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'accepted', 'discarded'))
);

CREATE TABLE company_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    slug TEXT NOT NULL,
    name TEXT,
    region TEXT NOT NULL DEFAULT '',
    careers_url TEXT,
    added_at TEXT NOT NULL,
    last_fetched_at TEXT,
    last_status TEXT,
    last_error TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (provider, slug, region)
);

CREATE TABLE searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT,
    filters_json TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    sources_ok INTEGER NOT NULL DEFAULT 0,
    sources_failed INTEGER NOT NULL DEFAULT 0,
    jobs_fetched INTEGER NOT NULL DEFAULT 0,
    jobs_new INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    errors_json TEXT
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    company_slug TEXT,
    external_id TEXT,
    company TEXT,
    title TEXT NOT NULL,
    description TEXT,
    location TEXT,
    work_model TEXT,
    contract_type TEXT,
    seniority TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    salary_period TEXT,
    posted_at TEXT,
    url TEXT,
    canonical_url TEXT,
    apply_url TEXT,
    language TEXT,
    fingerprint TEXT,
    content_hash TEXT,
    field_sources_json TEXT,
    requirements_json TEXT,
    suspicious_json TEXT,
    verification TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_verified_at TEXT,
    last_seen_search_id INTEGER,
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN ('discovered', 'shortlisted', 'prepared', 'submitted',
                          'interviewing', 'rejected', 'offer', 'closed')),
    ignored INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_jobs_canonical ON jobs (canonical_url);
CREATE INDEX idx_jobs_fingerprint ON jobs (fingerprint);
CREATE INDEX idx_jobs_source ON jobs (source, company_slug);

CREATE TABLE job_aliases (
    canonical_url TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs (id),
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    seen_at TEXT NOT NULL
);

CREATE TABLE search_results (
    search_id INTEGER NOT NULL REFERENCES searches (id),
    job_id TEXT NOT NULL REFERENCES jobs (id),
    outcome TEXT NOT NULL,
    PRIMARY KEY (search_id, job_id)
);

CREATE TABLE match_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs (id),
    profile_version INTEGER,
    score REAL,
    confidence REAL,
    recommendation TEXT NOT NULL,
    eliminated INTEGER NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_match_job ON match_results (job_id, created_at);

CREATE TABLE resumes (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('imported', 'generated')),
    language TEXT,
    target_roles_json TEXT NOT NULL,
    highlighted_skills_json TEXT NOT NULL,
    experience_ids_json TEXT NOT NULL,
    source_profile_version INTEGER,
    source_profile_hash TEXT,
    facts_fingerprint TEXT,
    content_hash TEXT NOT NULL,
    dir TEXT NOT NULL,
    md_path TEXT,
    text_path TEXT,
    pdf_path TEXT,
    docx_path TEXT,
    original_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE resume_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs (id),
    resume_id TEXT REFERENCES resumes (id),
    score REAL,
    decision TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs (id),
    resume_id TEXT REFERENCES resumes (id),
    resume_content_hash TEXT,
    package_dir TEXT NOT NULL,
    apply_url TEXT,
    mode TEXT NOT NULL DEFAULT 'prepared',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    submitted_at TEXT,
    submission_evidence TEXT
);

CREATE TABLE status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs (id),
    application_id TEXT,
    from_status TEXT,
    to_status TEXT NOT NULL,
    at TEXT NOT NULL,
    note TEXT,
    evidence TEXT
);
