-- Table privileges for the backend.
--
-- Newer Supabase projects no longer grant privileges on tables created in the SQL editor to the API roles
-- automatically. ContriMap's backend uses the service role (secret key), so it gets read/write access here.
-- anon and authenticated (browser keys) get nothing; row level security stays enabled as a second barrier.

grant usage on schema public to service_role;

grant select, insert, update, delete on table
  repository_heads, repository_snapshots, repository_metrics, issue_predictions,
  issue_analyses, similar_issues, explanations, user_profiles, feedback_events
to service_role;

grant usage, select on sequence feedback_events_id_seq to service_role;

revoke all on table
  repository_heads, repository_snapshots, repository_metrics, issue_predictions,
  issue_analyses, similar_issues, explanations, user_profiles, feedback_events
from anon, authenticated;
