// should wrap all auth-protected routes
import { Outlet } from "react-router";
import Navbar from "~/components/ui/navbar";

export default function ProtectedLayout() {
  return (
    <div>
      <Navbar />
      <h2>Protected Layout</h2>
      <Outlet />
    </div>
  );
}