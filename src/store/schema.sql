-- Run this once in the Supabase SQL editor.
--
-- Four tables. `profiles` maps each authenticated user to a role;
-- `approvals` and `completions` hold planning decisions; `reports` is the
-- shared intake for defects raised in the field. Everything else in the
-- system is reproducible from a seed and the cached timetable, so nothing
-- else belongs in a database.

-- ── roles ───────────────────────────────────────────────────────────────
--
-- Two roles, matching how a division actually works:
--
--   head      the divisional planning officer. Grants closures. A block takes
--             track out of service, so authorising one is an authority
--             decision, not a departmental one.
--   engineer  ENGG / TRD / S&T staff. Reports work as done. Cannot grant
--             closures.
--
-- Both can see everything: an engineer needs the whole plan to know when
-- their section is free, and hiding it would help nobody.

do $$
begin
    if not exists (select 1 from pg_type where typname = 'planner_role') then
        create type planner_role as enum ('head', 'engineer');
    end if;
end
$$;

create table if not exists profiles (
    id         uuid primary key references auth.users (id) on delete cascade,
    role       planner_role not null default 'engineer',
    full_name  text not null default '',
    department text not null default '',
    created_at timestamptz not null default now()
);

-- Every new sign-up gets a profile automatically, defaulting to the lower
-- privilege. Promoting someone to head is a deliberate act, never a default.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
    insert into public.profiles (id, full_name)
    values (new.id, coalesce(new.raw_user_meta_data ->> 'full_name', ''))
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

create or replace function public.current_role_is(wanted planner_role)
returns boolean language sql stable security definer set search_path = public as $$
    select exists (
        select 1 from public.profiles
        where id = auth.uid() and role = wanted
    );
$$;

-- ── decisions ───────────────────────────────────────────────────────────

create table if not exists approvals (
    instance_id text not null,
    section_id  text not null,
    start_iso   text not null,
    decided_by  text not null default 'unknown',
    decided_at  text not null,
    note        text not null default '',
    primary key (instance_id, section_id, start_iso)
);

create table if not exists completions (
    instance_id  text not null,
    task_id      text not null,
    completed_at text not null,
    completed_by text not null default 'unknown',
    note         text not null default '',
    primary key (instance_id, task_id)
);

-- ── field reports ───────────────────────────────────────────────────────
--
-- The shared front door. Today ENGG, TRD and S&T each raise work through
-- their own system, so nobody sees the other two requests until all three
-- closures are already booked on the same stretch of track. One table, read
-- by everybody, is what makes co-location possible in the first place.
--
-- A report is a REQUEST, not a scheduled job. It becomes work the planner
-- can place only once the divisional head accepts it.

do $$
begin
    if not exists (select 1 from pg_type where typname = 'report_status') then
        create type report_status as enum ('open', 'accepted', 'rejected');
    end if;
end
$$;

create table if not exists reports (
    id               text primary key,
    section_id       text not null,
    activity_type    text not null,
    summary          text not null,
    -- The department that owns the asset and does the work.
    department       text not null,
    -- Others who must attend: an OHE isolation for track work, a signal
    -- disconnection for point work. This column is the co-location signal —
    -- it is what tells the planner one closure can serve two departments.
    concerns         text[] not null default '{}',
    severity         smallint not null default 3 check (severity between 1 and 5),
    emergency        boolean not null default false,
    duration_minutes integer not null default 120 check (duration_minutes > 0),
    crew_required    smallint not null default 2 check (crew_required >= 1),
    detail           text not null default '',
    status           report_status not null default 'open',
    reported_by      text not null default 'unknown',
    reported_at      text not null,
    decided_by       text not null default '',
    decided_at       text not null default '',
    decision_note    text not null default ''
);

create index if not exists reports_status_idx  on reports (status);
create index if not exists reports_section_idx on reports (section_id);

create index if not exists approvals_instance_idx on approvals (instance_id);
create index if not exists completions_instance_idx on completions (instance_id);

-- ── row level security ──────────────────────────────────────────────────
--
-- Enforced in the database, not just in the UI. Hiding a button is a
-- courtesy; this is the actual control. An engineer who calls the REST API
-- directly still cannot grant a closure.

alter table profiles    enable row level security;
alter table approvals   enable row level security;
alter table completions enable row level security;
alter table reports     enable row level security;

drop policy if exists "read own profile"  on profiles;
drop policy if exists "read approvals"    on approvals;
drop policy if exists "head writes approvals" on approvals;
drop policy if exists "head deletes approvals" on approvals;
drop policy if exists "read completions"  on completions;
drop policy if exists "signed in writes completions" on completions;
drop policy if exists "signed in deletes completions" on completions;
drop policy if exists "demo full access"  on approvals;
drop policy if exists "demo full access"  on completions;
drop policy if exists "read reports"      on reports;
drop policy if exists "signed in files reports" on reports;
drop policy if exists "head decides reports" on reports;

-- Anyone signed in may read their own profile and the whole plan's decisions.
create policy "read own profile" on profiles
    for select using (auth.uid() = id);

create policy "read approvals" on approvals
    for select using (auth.role() = 'authenticated');

create policy "read completions" on completions
    for select using (auth.role() = 'authenticated');

-- Granting a closure is the head's decision alone.
create policy "head writes approvals" on approvals
    for insert with check (public.current_role_is('head'));

create policy "head deletes approvals" on approvals
    for delete using (public.current_role_is('head'));

-- Reporting work done is anyone signed in — engineers do the work.
create policy "signed in writes completions" on completions
    for insert with check (auth.role() = 'authenticated');

create policy "signed in deletes completions" on completions
    for delete using (auth.role() = 'authenticated');

-- Raising a defect is anyone signed in — an engineer walking the track is
-- the only person who will ever see a cracked fishplate first. Deciding what
-- to do about it is the head's, same as granting the closure it will need.
create policy "read reports" on reports
    for select using (auth.role() = 'authenticated');

create policy "signed in files reports" on reports
    for insert with check (auth.role() = 'authenticated');

create policy "head decides reports" on reports
    for update using (public.current_role_is('head'))
    with check (public.current_role_is('head'));

-- ── creating the two users ──────────────────────────────────────────────
--
-- In the Supabase dashboard: Authentication → Users → Add user, twice.
-- Then promote one of them:
--
--   update public.profiles set role = 'head', full_name = 'Divisional Officer'
--    where id = (select id from auth.users where email = 'head@example.com');
--
--   update public.profiles set role = 'engineer', full_name = 'Section Engineer',
--          department = 'ENGG'
--    where id = (select id from auth.users where email = 'engineer@example.com');
