-- ContriMap persistent store (contrimap_ml/store.py).
--
-- Cache tables share one shape: the text `key` encodes everything that invalidates the row
-- (commit SHA, issue content version, model version, LLM model, profile hash), so a new commit,
-- an edited issue or a retrained model simply produces a new key and old rows are never served.
-- `expires_at` is set only for time-sensitive data (resolved branch heads, similar-issue results).
--
-- Access: row level security is enabled with no policies, so the anon and authenticated roles
-- (browser keys) cannot read or write anything. Only the FastAPI backend, using the service-role
-- key, reaches these tables.

create table if not exists repository_heads (
  key text primary key,                 -- owner/name
  repository text, sha text, model_version text,
  data jsonb not null,                  -- {"sha": ...}
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists repository_snapshots (
  key text primary key,                 -- owner/name@sha:v<snapshot version>
  repository text, sha text, model_version text,
  data jsonb not null,                  -- files, imports, tests, manifests, packages, skills
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists repository_metrics (
  key text primary key,                 -- owner/name@sha:g<graph version>
  repository text, sha text, model_version text,
  data jsonb not null,                  -- pagerank, betweenness, communities, in-degree, summary
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists issue_predictions (
  key text primary key,                 -- owner/name#number:issue version:sha:model version
  repository text, sha text, model_version text,
  data jsonb not null,                  -- embedding, top files, difficulty/effort, actionability
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists issue_analyses (
  key text primary key,                 -- ...:profile hash
  repository text, sha text, model_version text,
  data jsonb not null,                  -- full issue analysis (without the LLM explanation)
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists similar_issues (
  key text primary key,                 -- owner/name#number:issue version
  repository text, sha text, model_version text,
  data jsonb not null,                  -- similar closed issues / merged PRs and the files they changed
  created_at timestamptz not null default now(),
  expires_at timestamptz                -- recent history changes, so rows expire
);

create table if not exists explanations (
  key text primary key,                 -- ...:LLM model:profile hash
  repository text, sha text, model_version text,
  data jsonb not null,                  -- {"source": "llm" | "template", "model": ..., "summary": ..., ...}
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists user_profiles (
  key text primary key,                 -- GitHub login or random browser id
  repository text, sha text, model_version text,
  data jsonb not null,                  -- level, tech stack, interests, learning goals, time budget, login
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists feedback_events (
  id bigserial primary key,
  user_id text not null,
  repository text not null,
  number integer not null,
  action text not null check (action in ('opened', 'saved', 'unsaved', 'dismissed', 'restored', 'completed')),
  title text default '',
  text text default '',
  created_at timestamptz not null default now()
);

create index if not exists feedback_events_user_time on feedback_events (user_id, created_at);
create index if not exists issue_predictions_repository on issue_predictions (repository, sha);
create index if not exists issue_analyses_repository on issue_analyses (repository, sha);
create index if not exists explanations_repository on explanations (repository);
create index if not exists similar_issues_expiry on similar_issues (expires_at);
create index if not exists repository_heads_expiry on repository_heads (expires_at);

alter table repository_heads enable row level security;
alter table repository_snapshots enable row level security;
alter table repository_metrics enable row level security;
alter table issue_predictions enable row level security;
alter table issue_analyses enable row level security;
alter table similar_issues enable row level security;
alter table explanations enable row level security;
alter table user_profiles enable row level security;
alter table feedback_events enable row level security;

-- Housekeeping: remove expired rows (schedule with pg_cron, or run by hand).
create or replace function contrimap_delete_expired() returns integer
language plpgsql security definer set search_path = public as $$
declare removed integer := 0; n integer;
begin
  delete from repository_heads where expires_at < now(); get diagnostics n = row_count; removed := removed + n;
  delete from similar_issues where expires_at < now(); get diagnostics n = row_count; removed := removed + n;
  return removed;
end $$;
revoke all on function contrimap_delete_expired() from public, anon, authenticated;
