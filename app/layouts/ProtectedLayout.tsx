// should wrap all auth-protected routes
import { Outlet } from "react-router";
import Navbar from "~/components/ui/navbar";
import { supabase } from "../supabaseClient";
import { useState, useEffect } from "react";
// import icon from "../assets/volarbear-icon.png";
// import name from "../assets/volarbear-name.png";
// import pfp from "../assets/profile-picture.png";
// import Search from "../components/ui/search";
import { useNavigate } from "react-router";

export default function ProtectedLayout() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [isLoggedin, setIsLoggedin] = useState(false);
  // temporary condition to test protected routes, replace with actual auth check
  // TODO: add auth check here and redirect to login if not authenticated
  useEffect(() => {
    const checkAuth = async () => {
      const { data, error } = await supabase.auth.getUser();
      if (error || !data.user) {
        //   // Redirect to login page if not authenticated
        //  navigate("/login");
        console.log("User not authenticated, redirecting to login...");
        setIsLoggedin(false);
        navigate("/login");
      } else {
        console.log("User authenticated");
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
