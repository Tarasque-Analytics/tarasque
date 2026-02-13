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
    <div className="navbar">
      <div className="navbar-logo">
        <Link to="/Dashboard">
          <img src={VolarLogo} alt="Volarbear Logo" className="h-12" />
        </Link>
      </div>
      <div className="navbar-title">
        <img src={VolarTitle} alt="Volarbear Title" className="h-12" />
      </div>
      <div className="navbar-search">
        <Search />
      </div>
      <div className="navbar-user">
        <UserIcon />
      </div>
    </div>
  );
}
