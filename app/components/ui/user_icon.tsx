import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { supabase } from "../../supabaseClient";
import type { User } from "@supabase/supabase-js";

/**
 * Profile menu for the navbar — an initials avatar that opens a small dropdown with
 * Profile settings (placeholder) and Log out. Initials are derived from the Supabase user
 * (getUser()); the avatar shows an empty circle until that async call resolves.
 */

// Prefer a full name from user metadata; otherwise derive initials from the email local-part
// (split on . _ - if present, else the first two characters).
function deriveInitials(user: User | null): string {
  const meta = (user?.user_metadata ?? {}) as { full_name?: string; name?: string };
  const name = (meta.full_name || meta.name || "").trim();
  if (name) {
    const parts = name.split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  const local = (user?.email ?? "").split("@")[0];
  if (!local) return "?";
  const segs = local.split(/[._-]+/).filter(Boolean);
  if (segs.length >= 2) return (segs[0][0] + segs[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}

export default function UserIcon() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => setUser(data.user ?? null));
  }, []);

  // Close on outside click / Escape while the menu is open.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const logout = async () => {
    await supabase.auth.signOut();
    setOpen(false);
    navigate("/login");
  };

  const initials = user ? deriveInitials(user) : "";

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={open ? "Close user menu" : "Open user menu"}
        aria-haspopup="menu"
        className="flex h-9 w-9 cursor-pointer select-none items-center justify-center rounded-full bg-(--text-primary) text-xs font-semibold text-(--ui-background)"
      >
        {initials}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-60 rounded-lg border border-(--panel-border) bg-(--ui-background) p-1.5 shadow-lg"
        >
          <div className="px-2.5 py-2">
            <p className="text-[10px] font-medium uppercase tracking-wide text-(--text-muted)">
              Signed in as
            </p>
            <p className="mt-0.5 truncate text-sm text-(--text-primary)">{user?.email ?? "—"}</p>
          </div>

          <div className="my-1 h-px bg-(--panel-border)" />

          {/* Profile settings — placeholder; there is no settings route yet.
              TODO: navigate to the profile settings route once it exists (e.g. /settings/profile). */}
          <button
            type="button"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex w-full items-center justify-between rounded-md px-2.5 py-2 text-sm text-(--text-secondary) hover:bg-(--track-bg) hover:text-(--text-primary)"
          >
            Profile settings
            <span className="text-[10px] uppercase tracking-wide text-(--text-muted)">Soon</span>
          </button>

          <button
            type="button"
            role="menuitem"
            onClick={logout}
            className="mt-0.5 flex w-full items-center rounded-md px-2.5 py-2 text-sm font-medium text-(--neg) hover:bg-(--track-bg)"
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
