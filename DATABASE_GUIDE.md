# Setup
   ## Prerequisites
   Before starting, ensure you have the following installed:
   *[Docker Desktop](https://www.docker.com/products/docker-desktop/) (Must be running)
   * [Supabase CLI](https://supabase.com/docs/guides/cli)
   * [Node.js](https://nodejs.org/) (v18 or higher)
   ## Start Supabase
   Type this in terminal while in the volarbmodel cd
      supabase start
   ## Initialize Database
   Type this into terminal
      supabase db reset
   You can manage the local database visually at: http://localhost:54323
# Collaboration Workflow
To keep the database in sync across the team, we use Migrations.
   ## Adding a new Table or Column
   1. **Create a new migration file:**
      supabase migration new name_of_your_change
   2. **Edit SQL file created in supabase/migrations/ as needed**
   3. **Apply the change locally**
      supabase db reset
   ## Alternative
   If you want to create tables through the local Supabase UI, run:
      supabase db diff -f table_name
   in order to 




