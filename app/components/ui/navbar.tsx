// app/assets/volar-logo.png
// app/assets/volar-title.png
// app/components/ui/searchbar.tsx
// app/components/ui/user_icon.tsx

// assets
import notATurtle from "~/assets/turtle.svg";
import Home from "~/assets/home.svg";
// components
import Search from "./search";
import UserIcon from "./user_icon";
import { Link } from "react-router";

// left corner logo, centered company title, 3/4ths-centered searchbar, right corner profile icon
export default function Navbar() {
  return (
    <div className="navbar h-20 p-4 grid grid-cols-20 gap-8">
      <div className="flex items-center col-span-1 justify-start h-10">
        <Link to="/Dashboard">
          <img src={Home} alt="Home" className="h-10" />
        </Link>
      </div>
      <div className="flex items-center col-span-11 justify-start h-12">
        

        <h1 className = "text-2xl font-bold tracking-tight text-gray-800">Tarasque Risk & Analytics</h1>
        <img src={notATurtle} alt="definitely a tarasque (change when u get real tarasque)" className="h-12" />
      </div>
      <div className="flex items-center col-span-8 justify-end h-12">
        {/* moved search bar down here, put wherever */}
        <Search />
        <UserIcon />
      </div>
      

    </div>
  );
}
