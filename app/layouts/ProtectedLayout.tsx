// should wrap all auth-protected routes
import { Outlet } from "react-router";
// import Navbar from "~/components/ui/navbar";
import icon from "../assets/volarbear-icon.png";
import name from "../assets/volarbear-name.png";
import pfp from "../assets/profile-picture.png";
import Search from "../components/ui/search";

export default function ProtectedLayout() {
  return (
    <div className="p-6">
      <div style={{ alignContent: "center"}} className="grid grid-cols-1 lg:grid-cols-3">
        {/* <Navbar /> */}
        {/* The volarbear icon top left */}
        <div style={{ display: "flex", justifyContent: "flex-start", alignItems: "flex-start" }}>
          <img
            src={icon}
            alt="Volarbear"
            style={{
              width: "75px",
              height: "auto",
              display: "block",
            }}
          />
        </div>
        {/* The volarbear name top center */}
        <div style={{ display: "flex", justifyContent: "center", alignItems: "flex-start", gap: "1rem"}}>
          <img
            src={name}
            alt="Volarbear"
            style={{
              width: "200px",
              height: "auto",
              display: "block",
            }}
          />
        </div>
        {/* pfp top right */}
        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "flex-end" }}>
          <Search />
          <img
            src={pfp}
            alt="Volarbear"
            style={{
              width: "75px",
              height: "auto",
              display: "block",
            }}
          />
        </div>
      </div>
      <div>
        <Outlet />
      </div>
    </div>
  );
}
