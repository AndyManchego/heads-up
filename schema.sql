-- Run this once in Supabase: Dashboard > SQL Editor > New query > paste > Run

create table if not exists bills (
  id                 text primary key,          -- e.g. "119-hr-1234"
  congress           int  not null,
  bill_type          text not null,             -- HR, S, HJRES, SJRES
  number             text not null,
  title              text,
  stage              text,                      -- "Became law", "Passed Senate", etc.
  latest_action      text,
  latest_action_date date,
  text_version       text,                      -- which version of the text we summarized
  summary            jsonb,                     -- the summary card
  congress_url       text,
  updated_at         timestamptz default now()
);

create index if not exists bills_action_date_idx on bills (latest_action_date desc);

-- Anyone can READ bills (the website uses this). Only the script, using the
-- secret service key, can WRITE.
alter table bills enable row level security;
drop policy if exists "public read" on bills;
create policy "public read" on bills for select using (true);
