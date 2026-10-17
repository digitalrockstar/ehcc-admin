-- EHCC Admin schema change for team-balance rounding settlements
-- Run against the Neon PostgreSQL database. Safe to re-run.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_settlements_kind'
      AND conrelid = to_regclass('public.settlements')
  ) THEN
    ALTER TABLE public.settlements DROP CONSTRAINT ck_settlements_kind;
  END IF;
  ALTER TABLE public.settlements
    ADD CONSTRAINT ck_settlements_kind
    CHECK (kind IN ('reimbursement', 'collection', 'team_balance'));
END $$;
