import { useState, useEffect } from "react";
import { supabase } from "../supabaseClient";
import { Link, useNavigate } from "react-router";
export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  // Handle the return leg of the Google OAuth round-trip. On success Supabase appends the
  // session to this URL and fires SIGNED_IN, so we forward to the dashboard. A cancelled or
  // denied sign-in returns here with no session, so the user simply lands back on the login
  // page (instead of the site's base URL).
  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_IN" && session) {
        navigate("/dashboard");
      }
    });
    return () => data.subscription.unsubscribe();
  }, [navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
    setIsLoading(false);

    if (authError) {
      setError("Incorrect email or password");
      return;
    }

    // Login successful, redirect to home
    navigate("/dashboard");
  };

  const handleOAuthSignIn = async () => {
    setError("");
    setIsLoading(true);

    const { error: authError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        // Return to the login page after the Google round-trip. If the user cancels, they land
        // back here rather than on the site's base URL. NOTE: this exact URL must be in the
        // Supabase project's redirect allow-list, otherwise Supabase falls back to the Site URL.
        redirectTo: `${window.location.origin}/login`,
      },
    });

    if (authError) {
      setError("Failed to sign in with Google");
      setIsLoading(false);
    }
  };

  return (
    <div className="page-center">
      <div className="auth-card">
        <h1 className="page-title">Login</h1>

        {error && (
          <div className="error-box">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="form-field">
            <label className="form-label">Email</label>
            <input
              type="email"
              placeholder="Enter your email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="form-input"
              required
            />
          </div>

          <div className="form-field">
            <label className="form-label">Password</label>
            <input
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="form-input"
              required
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="primary-button"
          >
            {isLoading ? "Logging in..." : "Login"}
          </button>

          <div className="divider-container">
            <div className="divider-line" />
            <span className="divider-text">OR</span>
            <div className="divider-line" />
          </div>

          <button
            type="button"
            onClick={handleOAuthSignIn}
            disabled={isLoading}
            className="oauth-button"
          >
            
            <img
              src="app\assets\Google__G__logo.svg"
              alt="Google Logo"
            />
            Continue with Google
          </button>

          <Link to="/Register" className="text-link block text-center">
            Don't have an account yet? Register here.
          </Link>
        </form>
      </div>
    </div>
  );
}
