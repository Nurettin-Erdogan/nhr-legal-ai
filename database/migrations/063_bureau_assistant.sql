\set ON_ERROR_STOP on
BEGIN;
CREATE TABLE public.office_bureau_decisions (
  id UUID PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  proposal_key TEXT NOT NULL CHECK (length(proposal_key) <= 240),
  status TEXT NOT NULL CHECK (status IN ('approved', 'dismissed')),
  task_id UUID REFERENCES public.office_tasks(id) ON DELETE SET NULL,
  event_id UUID REFERENCES public.office_calendar_events(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(owner_id, proposal_key)
);
ALTER TABLE public.office_bureau_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.office_bureau_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY bureau_owner ON public.office_bureau_decisions
  USING (owner_id = public.app_current_user_id())
  WITH CHECK (owner_id = public.app_current_user_id());
GRANT SELECT, INSERT ON public.office_bureau_decisions TO nhr_runtime;
COMMIT;
