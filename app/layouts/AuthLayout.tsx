import { Outlet } from "react-router";

export default function AuthLayout() {
  return (
    <div>
      <h2>Auth Layout</h2>
      <Outlet />
    </div>
  );
}
