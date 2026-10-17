-- EHCC Admin player-credit and team-balance schema upgrade (Neon PostgreSQL).
-- Safe to re-run; existing transaction and settlement history is preserved.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_settlements_kind' AND conrelid=to_regclass('public.settlements')) THEN
    ALTER TABLE public.settlements DROP CONSTRAINT ck_settlements_kind;
  END IF;
  ALTER TABLE public.settlements ADD CONSTRAINT ck_settlements_kind
    CHECK (kind IN ('reimbursement','collection','team_balance'));
END $$;
DROP INDEX IF EXISTS public.uq_active_settlement;
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_reimbursement ON public.settlements (transaction_id, account_id)
  WHERE status='active' AND kind='reimbursement';
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_team_balance ON public.settlements (transaction_id, kind)
  WHERE status='active' AND kind='team_balance';
CREATE TABLE IF NOT EXISTS public.player_credits (
  id SERIAL PRIMARY KEY,
  team_id INTEGER NOT NULL REFERENCES public.teams(id),
  account_id INTEGER NOT NULL REFERENCES public.accounts(id),
  source_transaction_id INTEGER REFERENCES public.transactions(id) ON DELETE SET NULL,
  original_amount NUMERIC(12,2) NOT NULL CHECK (original_amount > 0),
  remaining_amount NUMERIC(12,2) NOT NULL CHECK (remaining_amount >= 0 AND remaining_amount <= original_amount),
  note VARCHAR(200),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_player_credits_team_id ON public.player_credits(team_id);
CREATE INDEX IF NOT EXISTS ix_player_credits_account_id ON public.player_credits(account_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_player_credit_source_account ON public.player_credits(source_transaction_id, account_id);
CREATE TABLE IF NOT EXISTS public.player_credit_movements (
  id SERIAL PRIMARY KEY,
  credit_id INTEGER NOT NULL REFERENCES public.player_credits(id),
  kind VARCHAR(12) NOT NULL CHECK (kind IN ('created','application','team_transfer','adjustment')),
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  transaction_id INTEGER REFERENCES public.transactions(id) ON DELETE SET NULL,
  allocation_id INTEGER REFERENCES public.allocations(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reversed_at TIMESTAMPTZ
);
ALTER TABLE public.player_credit_movements ADD COLUMN IF NOT EXISTS reversed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_player_credit_movements_credit_id ON public.player_credit_movements(credit_id);
