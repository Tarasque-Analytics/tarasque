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

// left corner logo, centered company title, 3/4ths-centered searchbar, right corner profile icon
export default function Navbar() {
  return (
    <div className="navbar h-20 p-4 grid grid-cols-12 gap-8">
      <div className="flex items-center justify-start col-span-4 h-12">
        <Link to="/Dashboard">
          <img src={VolarLogo} alt="Volarbear Logo" className="h-12" />
        </Link>
      </div>
      <div className="flex items-center justify-center col-span-4 h-12">
        <img src={VolarTitle} alt="Volarbear Title" className="h-12" />
      </div>
      <div className="flex items-center justify-start col-span-3 h-12">
        <Search />
      </div>
      <div className="flex items-center justify-end h-12">
        <UserIcon />
      </div>
    </div>
  );
}
