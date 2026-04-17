import Icon from "~/assets/user-icon.svg";
import { useEffect, useState } from "react";
import { supabase } from "../../supabaseClient";

export default function UserIcon() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("Logged in user");

  useEffect(() => {
    const loadUser = async () => {
      const { data } = await supabase.auth.getUser();
      setEmail(data.user?.email ?? "Logged in user");
    };

    loadUser();
  }, []);

  const logout = async () => {
    await supabase.auth.signOut();
    setOpen(false);
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Open user menu"
        className="bg-white flex h-12 items-center justify-center"
      >
        <img src={Icon} alt="User Icon" className="bg-white flex h-12" />
      </button>

      {open ? (
        <div className="absolute right-0 mt-2 w-72 rounded-lg border border-gray-200 bg-white shadow-lg z-50 p-3">
          <p className="text-xs uppercase tracking-wide text-gray-500 mb-1">Signed in as</p>
          <p className="text-sm text-gray-800 break-all mb-3">{email}</p>
          <button
            type="button"
            onClick={logout}
            className="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600 transition-colors w-full"
          >
            Logout
          </button>
        </div>
      ) : null}
    </div>
  );
}
