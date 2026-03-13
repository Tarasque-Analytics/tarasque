```markdown
# Project Setup

## Prerequisites
Before starting, ensure you have the following installed:
* [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Must be running)
* [Supabase CLI](https://supabase.com/docs/guides/cli)
* [Node.js](https://nodejs.org/) (v18 or higher)

---

## Start Supabase
Type this in the terminal while in the `volarbmodal` directory:
```bash
supabase start

```

## Initialize Database

Type this into the terminal:

```bash
supabase db reset

```

You can manage the local database visually at: [http://localhost:54323](https://www.google.com/search?q=http://localhost:54323)

---

# Collaboration Workflow

To keep the database in sync across the team, we use **Migrations**.

## Adding a New Table or Column

1. **Create a new migration file:**
```bash
supabase migration new name_of_your_change

```


2. **Edit the SQL file** created in `supabase/migrations/` as needed.
3. **Apply the change locally:**
```bash
supabase db reset

```



## Alternative (UI to Code)

If you prefer to create tables through the local Supabase UI, run:

```bash
supabase db diff -f table_name

```

This will generate a migration file to sync the UI changes with the `migrations` folder for the rest of the team.

```
