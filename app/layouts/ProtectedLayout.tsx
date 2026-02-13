// should wrap all auth-protected routes
import { Outlet } from "react-router";
import Navbar from "~/components/ui/navbar";
// import icon from "../assets/volarbear-icon.png";
// import name from "../assets/volarbear-name.png";
// import pfp from "../assets/profile-picture.png";
// import Search from "../components/ui/search";

export default function ProtectedLayout() {
  return (
    <div className="p-6">
      <Navbar />
      <Outlet />
    </div>
  );
}
