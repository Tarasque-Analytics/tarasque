CREATE TABLE stonks (
  id bigint primary key generated always as identity,
  name text not null,
  is_complete boolean default false,
  inserted_at timestamptz default now()
);