-- SiteScribe cloud schema. Supabase tracks this file independently of Alembic.
create table public.profiles (
  id uuid primary key,
  email varchar(320) not null unique,
  display_name varchar(200),
  last_login_at timestamptz,
  last_active_at timestamptz,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table public.workspaces (
  id uuid primary key,
  name varchar(200) not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table public.auth_sessions (
  id uuid primary key,
  profile_id uuid not null references public.profiles(id) on delete cascade,
  session_id_hash varchar(64) not null unique,
  access_token_ciphertext text not null,
  refresh_token_ciphertext text not null,
  access_token_expires_at timestamptz not null,
  session_expires_at timestamptz not null,
  created_at timestamptz not null,
  last_seen_at timestamptz not null,
  revoked_at timestamptz
);
create index ix_auth_sessions_profile_expiry
  on public.auth_sessions(profile_id, session_expires_at);
create index ix_auth_sessions_revoked_at on public.auth_sessions(revoked_at);

create table public.workspace_members (
  id uuid primary key,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  profile_id uuid not null references public.profiles(id) on delete cascade,
  role varchar(6) not null check (role in ('admin', 'member')),
  status varchar(8) not null check (status in ('pending', 'active', 'disabled')),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  constraint uq_workspace_member_profile unique (workspace_id, profile_id)
);
create index ix_workspace_members_profile_status
  on public.workspace_members(profile_id, status);

create table public.projects (
  id uuid primary key,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  name varchar(300) not null,
  project_number varchar(100),
  address text,
  client varchar(300),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  archived_at timestamptz,
  purge_after timestamptz,
  constraint ck_projects_archive_pair check (
    (archived_at is null and purge_after is null) or
    (archived_at is not null and purge_after is not null)
  )
);
create index ix_projects_workspace_name_id
  on public.projects(workspace_id, lower(name), id);
create index ix_projects_purge_after on public.projects(purge_after);

create table public.visits (
  id uuid primary key,
  project_id uuid not null references public.projects(id) on delete cascade,
  visit_date date not null,
  report_number varchar(100),
  engineer varchar(200),
  visit_time varchar(100),
  conditions text,
  attendees json not null,
  summary text,
  report_options json not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  archived_at timestamptz,
  purge_after timestamptz,
  constraint ck_visits_archive_pair check (
    (archived_at is null and purge_after is null) or
    (archived_at is not null and purge_after is not null)
  )
);
create index ix_visits_project_order
  on public.visits(project_id, visit_date, created_at, id);
create index ix_visits_purge_after on public.visits(purge_after);

create table public.items (
  id uuid primary key,
  visit_id uuid not null references public.visits(id) on delete cascade,
  number integer not null,
  position integer not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  constraint uq_items_visit_number unique (visit_id, number)
);
create index ix_items_visit_position on public.items(visit_id, position, id);

create table public.observations (
  id uuid primary key,
  item_id uuid not null references public.items(id) on delete cascade,
  sequence integer not null,
  description text not null,
  caption text,
  severity varchar(50),
  tags json not null,
  action text,
  include_in_report boolean not null,
  plan_page integer,
  plan_x double precision,
  plan_y double precision,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  constraint uq_observations_item_sequence unique (item_id, sequence)
);
create index ix_observations_item_sequence
  on public.observations(item_id, sequence);

create table public.files (
  id uuid primary key,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid references public.projects(id) on delete cascade,
  visit_id uuid references public.visits(id) on delete cascade,
  kind varchar(50) not null,
  storage_key text not null unique,
  mime_type varchar(255) not null,
  size_bytes bigint not null check (size_bytes >= 0),
  sha256 varchar(64) not null,
  original_filename varchar(500) not null,
  created_by_id uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null,
  updated_at timestamptz not null
);
create index ix_files_workspace_project_visit
  on public.files(workspace_id, project_id, visit_id);
create index ix_files_kind on public.files(kind);

create table public.observation_files (
  observation_id uuid not null references public.observations(id) on delete cascade,
  file_id uuid not null references public.files(id) on delete cascade,
  media_role varchar(50) not null,
  position integer not null,
  primary key (observation_id, file_id),
  constraint uq_observation_files_position unique (observation_id, position)
);

create table public.plans (
  id uuid primary key,
  visit_id uuid not null references public.visits(id) on delete cascade,
  file_id uuid not null unique references public.files(id) on delete cascade,
  page_count integer not null,
  plan_metadata json not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);
create index ix_plans_visit_id on public.plans(visit_id);

create table public.exports (
  id uuid primary key,
  project_id uuid references public.projects(id) on delete cascade,
  visit_id uuid references public.visits(id) on delete cascade,
  file_id uuid references public.files(id) on delete set null,
  export_type varchar(50) not null,
  status varchar(8) not null check (status in ('pending', 'building', 'complete', 'failed')),
  error text,
  created_by_id uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  constraint ck_exports_has_resource check (
    project_id is not null or visit_id is not null
  )
);
create index ix_exports_project_visit on public.exports(project_id, visit_id);

create table public.audit_events (
  id uuid primary key,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  actor_id uuid references public.profiles(id) on delete set null,
  action varchar(100) not null,
  resource_type varchar(50),
  resource_id uuid,
  created_at timestamptz not null,
  safe_metadata json not null
);
create index ix_audit_events_workspace_created
  on public.audit_events(workspace_id, created_at);

create table public.backup_runs (
  id uuid primary key,
  started_at timestamptz not null,
  finished_at timestamptz,
  status varchar(8) not null check (status in ('running', 'complete', 'failed')),
  object_count integer not null,
  byte_count bigint not null,
  manifest_sha256 varchar(64),
  error text
);
create index ix_backup_runs_started on public.backup_runs(started_at);

-- The Flask server is the sole data boundary. Block browser/Data API access
-- to application tables; the direct database connection remains authoritative.
alter table public.profiles enable row level security;
alter table public.auth_sessions enable row level security;
alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.projects enable row level security;
alter table public.visits enable row level security;
alter table public.items enable row level security;
alter table public.observations enable row level security;
alter table public.files enable row level security;
alter table public.observation_files enable row level security;
alter table public.plans enable row level security;
alter table public.exports enable row level security;
alter table public.audit_events enable row level security;
alter table public.backup_runs enable row level security;
