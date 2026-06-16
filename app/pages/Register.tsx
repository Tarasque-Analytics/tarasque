import { Link } from "react-router";
import { useState, useEffect } from "react";
import { supabase } from "../supabaseClient";
import { useNavigate } from "react-router";
export default function Register() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [reenterPassword, setReenterPassword] = useState("");
  const [passwordConfirmed, setPasswordConfirmed] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [error, setError] = useState("");

  // Handle the return leg of the Google OAuth round-trip. On success Supabase appends the
  // session to this URL and fires SIGNED_IN, so we forward to the dashboard. A cancelled or
  // denied sign-in returns here with no session, so the user simply lands back on the register
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
    setIsLoading(true);
    const { error } = await supabase.auth.signUp({
      email,
      password,
    });
    if (error) {
      console.error("Registration error:", error);
    }
    setIsLoading(false);
    navigate("/login");
  };

  const handleOAuthSignIn = async () => {
    setError("");
    setIsLoading(true);

    const { error: authError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        // Return to the register page after the Google round-trip. If the user cancels, they land
        // back here rather than on the site's base URL. NOTE: this exact URL must be in the
        // Supabase project's redirect allow-list, otherwise Supabase falls back to the Site URL.
        redirectTo: `${window.location.origin}/register`,
      },
    });

    if (authError) {
      setError("Failed to sign in with Google");
      setIsLoading(false);
    }
  };

  useEffect(() => {
    setPasswordConfirmed(password !== "" && password === reenterPassword);
  }, [password, reenterPassword]);

  function validateEmail(em: string) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(em);
  }

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="p-8 rounded-lg shadow-lg w-96 bg-neutral-100 dark:bg-neutral-800">
        <h1 className="text-2xl font-bold text-center mb-6">Register</h1>

        {error && (
          <div className="error-box">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Email</label>
            <input
              type="email"
              placeholder="Enter your email"
              value={email}
              onChange={(e) => {
                const v = e.target.value;
                setEmail(v);
                setEmailError(
                  v === "" || validateEmail(v) ? "" : "Please enter a valid email address.",
                );
              }}
              className="w-full px-4 py-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500
              bg-white dark:bg-neutral-900 text-neutral-900 dark:text-white
              placeholder-neutral-400 dark:placeholder-neutral-500
              border border-neutral-300 dark:border-neutral-700"
              required
            />
            {emailError ? <p className="text-xs text-red-500 dark:text-red-400 mt-1">{emailError}</p> : null}
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Password</label>
            <input
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500
              bg-white dark:bg-neutral-900 text-neutral-900 dark:text-white
              placeholder-neutral-400 dark:placeholder-neutral-500
              border border-neutral-300 dark:border-neutral-700"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Confirm Password</label>
            <input
              type="password"
              placeholder="Confirm your password"
              value={reenterPassword}
              onChange={(e) => setReenterPassword(e.target.value)}
              className="w-full px-4 py-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500
              bg-white dark:bg-neutral-900 text-neutral-900 dark:text-white
              placeholder-neutral-400 dark:placeholder-neutral-500
              border border-neutral-300 dark:border-neutral-700"
              required
            />
            {reenterPassword ? (
              password === reenterPassword ? (
                <p className="text-xs text-green-600 dark:text-green-400 mt-1">Passwords match</p>
              ) : (
                <p className="text-xs text-red-500 dark:text-red-400 mt-1">Passwords do not match</p>
              )
            ) : null}
          </div>

          <button
            type="submit"
            disabled={isLoading || !passwordConfirmed}
            className="cursor-pointer disabled:cursor-default w-full bg-blue-500 hover:bg-blue-600 text-white font-medium py-2 rounded-lg transition disabled:opacity-50"
          >
            {isLoading ? "Registering..." : "Register"}
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

          <Link to="/login" className="text-sm text-blue-500 hover:underline">
            Already have an account? Login here.
          </Link>
        </form>
      </div>
    </div>
  );
}
