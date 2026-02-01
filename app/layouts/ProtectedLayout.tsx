// should wrap all auth-protected routes
import { Outlet } from "react-router";

export default function ProtectedLayout() {
  return (
    <div>
      <h2>Protected Layout</h2>
      <Outlet />
    </div>
  );
}