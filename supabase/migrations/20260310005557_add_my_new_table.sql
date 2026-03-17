
  create table "public"."test import" (
    "Index" bigint not null,
    "Customer Id" text not null,
    "First Name" text not null,
    "Last Name" text not null,
    "Company" text not null,
    "City" text not null,
    "Country" text not null,
    "Phone 1" text not null,
    "Phone 2" text not null,
    "Email" text not null,
    "Subscription Date" text not null,
    "Website" text not null
      );


alter table "public"."test import" enable row level security;

CREATE UNIQUE INDEX "test import_pkey" ON public."test import" USING btree ("Index", "Customer Id", "First Name", "Last Name", "Company", "City", "Country", "Phone 1", "Phone 2", "Email", "Subscription Date", "Website");

alter table "public"."test import" add constraint "test import_pkey" PRIMARY KEY using index "test import_pkey";

grant delete on table "public"."test import" to "anon";

grant insert on table "public"."test import" to "anon";

grant references on table "public"."test import" to "anon";

grant select on table "public"."test import" to "anon";

grant trigger on table "public"."test import" to "anon";

grant truncate on table "public"."test import" to "anon";

grant update on table "public"."test import" to "anon";

grant delete on table "public"."test import" to "authenticated";

grant insert on table "public"."test import" to "authenticated";

grant references on table "public"."test import" to "authenticated";

grant select on table "public"."test import" to "authenticated";

grant trigger on table "public"."test import" to "authenticated";

grant truncate on table "public"."test import" to "authenticated";

grant update on table "public"."test import" to "authenticated";

grant delete on table "public"."test import" to "postgres";

grant insert on table "public"."test import" to "postgres";

grant references on table "public"."test import" to "postgres";

grant select on table "public"."test import" to "postgres";

grant trigger on table "public"."test import" to "postgres";

grant truncate on table "public"."test import" to "postgres";

grant update on table "public"."test import" to "postgres";

grant delete on table "public"."test import" to "service_role";

grant insert on table "public"."test import" to "service_role";

grant references on table "public"."test import" to "service_role";

grant select on table "public"."test import" to "service_role";

grant trigger on table "public"."test import" to "service_role";

grant truncate on table "public"."test import" to "service_role";

grant update on table "public"."test import" to "service_role";


