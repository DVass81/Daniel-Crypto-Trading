create table if not exists crypto_bot_state (
  id text primary key,
  payload jsonb not null default '{}'::jsonb,
  updated_at timestamp with time zone default now()
);

create table if not exists crypto_bot_events (
  id bigint generated always as identity primary key,
  created_at timestamp with time zone default now(),
  kind text not null,
  payload jsonb not null default '{}'::jsonb
);

create index if not exists crypto_bot_events_created_idx
  on crypto_bot_events (created_at desc);
