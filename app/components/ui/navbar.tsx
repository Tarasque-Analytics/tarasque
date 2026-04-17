// app/assets/volar-logo.png
// app/assets/volar-title.png
// app/components/ui/searchbar.tsx
// app/components/ui/user_icon.tsx

// assets
import VolarLogo from "~/assets/volarbear-logo.png";
import VolarTitle from "~/assets/volarbear-title.png";

// components
import Search from "./search";
import UserIcon from "./user_icon";
import { Link } from "react-router";
import { supabase } from "../../supabaseClient";
import { useState } from "react";

// left corner logo, centered company title, 3/4ths-centered searchbar, right corner profile icon
export default function Navbar() {
  const [open, setOpen] = useState(false);
  const logout = async () => {
    const { error } = await supabase.auth.signOut();
  };

  return (
    <div className="navbar h-20 p-4 grid grid-cols-12 gap-8">
      <div className="flex items-center col-span-2 justify-start h-12">
        <Link to="/Dashboard">
          <img src={VolarLogo} alt="Volarbear Logo" className="h-12" />
        </Link>
      </div>
      <div className="flex items-center col-span-3 justify-start h-12">
        <Search />
      </div>
      <div className="flex items-center col-span-2 justify-center h-12">
        <img src={VolarTitle} alt="Volarbear Title" className="h-12" />
      </div>
      <div className="flex items-center col-span-5 justify-end h-12">
        {/* temporary logout button for peace of mind, move elsewhere */}
        <button
          onClick={logout}
          className="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600 transition-colors"
        >
          Logout
        </button>
        <UserIcon />
      </div>
    </div>
  );
}
