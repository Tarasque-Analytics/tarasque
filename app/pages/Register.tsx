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
  const [hasUpperLowerCase, setHasUpperLowerCase] = useState(false);
  const [hasNumber, setHasNumber] = useState(false);
  const [hasSpecialChar, setHasSpecialChar] = useState(false);
  const [emailError, setEmailError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    console.log("Register attempt:", { email, password });
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

  useEffect(() => {
    const strengthOk = checkPasswordStrength(password);
    setPasswordConfirmed(password !== "" && password === reenterPassword && strengthOk);
  }, [password, reenterPassword]);

  function validateEmail(em: string) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(em);
  }

  function checkPasswordStrength(pw: string): boolean {
    let hasCapital = false;
    let hasNumber = false;
    let hasSpecial = false;
    let hasLower = false;
    for (let i = 0; i < pw.length; i++) {
      const char = pw.charAt(i);
      hasLower = hasLower || (char >= "a" && char <= "z");
      hasCapital = hasCapital || (char >= "A" && char <= "Z");
      hasNumber = hasNumber || (char >= "0" && char <= "9");
      hasSpecial = hasSpecial || "!@#$%^&*()_+-=[]{}|;':\"\\,.<>/?".includes(char);
    }

    setHasUpperLowerCase(hasCapital && hasLower);
    setHasNumber(hasNumber);
    setHasSpecialChar(hasSpecial);

    return hasCapital && hasNumber && hasSpecial && hasLower;
  }

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="p-8 rounded-lg shadow-lg w-96 bg-neutral-100 dark:bg-neutral-800">
        <h1 className="text-2xl font-bold text-center mb-6">Register</h1>

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
              onChange={(e) => {
                const v = e.target.value;
                setPassword(v);
                checkPasswordStrength(v);
              }}
              className="w-full px-4 py-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 
              bg-white dark:bg-neutral-900 text-neutral-900 dark:text-white 
              placeholder-neutral-400 dark:placeholder-neutral-500 
              border border-neutral-300 dark:border-neutral-700"
              required
            />
          </div>

          <div>
            <label className={`block text-xs font-medium mb-1 ${password.length >= 8 ? "text-green-500 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
              Must be at least 8 characters long
            </label>
            <label className={`block text-xs font-medium mb-1 ${hasUpperLowerCase ? "text-green-500 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
              Must include uppercase and lowercase letters
            </label>
            <label className={`block text-xs font-medium mb-1 ${hasNumber ? "text-green-500 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
              Must include at least one number
            </label>
            <label className={`block text-xs font-medium mb-1 ${hasSpecialChar ? "text-green-500 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
              Must include a special character
            </label>
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

          <Link to="/login" className="text-sm text-blue-500 hover:underline">
            Already have an account? Login here.
          </Link>
        </form>
      </div>
    </div>
  );
}
