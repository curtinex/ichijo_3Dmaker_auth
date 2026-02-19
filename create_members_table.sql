-- Create members table for subscription/trial management
-- Run this in Supabase SQL editor (Query) or psql connected to your database
create extension if not exists pgcrypto;

create table if not exists public.members (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  email text,
  plan text not null default 'free', -- 'free' or 'paid'
  trial_expires timestamptz,
  stripe_customer_id text,
  stripe_subscription_id text,
  status text default 'inactive', -- 'active', 'past_due', 'inactive'
  has_had_trial boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_members_email on public.members (email);

-- Optional: a function to update updated_at on change
create or replace function public.trigger_set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists set_updated_at on public.members;
create trigger set_updated_at
  before update on public.members
  for each row
  execute function public.trigger_set_updated_at();
