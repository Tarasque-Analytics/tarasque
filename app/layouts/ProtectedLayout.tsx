// should wrap all auth-protected routes
import { Outlet } from "react-router";
import Navbar from "~/components/ui/navbar";
import { supabase } from "../supabaseClient";
import { useState, useEffect } from "react";
import { useNavigate } from "react-router";

export default function ProtectedLayout() {
  const navigate = useNavigate();
  const [, setLoading] = useState(true);
  const [, setIsLoggedin] = useState(false);
  // Client-side auth gate: redirect to /login if there's no valid Supabase session.
  useEffect(() => {
    const checkAuth = async () => {
      const { data, error } = await supabase.auth.getUser();
      if (error || !data.user) {
        setIsLoggedin(false);
        navigate("/login");
      } else {
        setIsLoggedin(true);
      }
      setLoading(false);
    };
    checkAuth();
  }, []);

  // Navbar sits at the top with no padding above it so its `sticky top-0` pins flush to the
  // viewport; page content gets the padding via `.protected-content`.
  return (
    <div className="protected-layout">
      <Navbar />
      <main className="protected-content">
        <Outlet />
      </main>
    </div>
  );
}
