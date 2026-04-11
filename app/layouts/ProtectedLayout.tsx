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
  useEffect (() => { 
    const checkAuth = async () => {
    const { data, error } = await supabase.auth.getUser();
    if (!error || data.user) {
    //   // Redirect to login page if not authenticated
    //  navigate("/login");
      console.log("User not authenticated, redirecting to login...");
      setIsLoggedin(false);
    }
    else {
      console.log("User authenticated");  
      setIsLoggedin(true);
    }
    setLoading(false);
  }
  checkAuth();
}, []);
  
  // Remove later to navigate to login page instead of showing not authenticated message
    if (!isLoggedin) {
    return(
      <div className="flex items-center justify-center min-h-screen bg-gray-100">
        <div className="bg-white p-8 rounded-lg shadow-lg w-96">
          <h1 className="text-2xl font-bold text-center mb-6">Not Authenticated</h1>
        </div>
      </div>

    );
  }
    else if (isLoggedin) {
        return (
    <div className="protected-layout">
      <Navbar />
      <Outlet />
    </div>
  );
    }
  }

