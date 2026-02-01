import { Link } from "react-router";
import { useState, useEffect } from "react";

export default function Register() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [reenterPassword, setReenterPassword] = useState("");
  const [passwordConfirmed, setPasswordConfirmed] = useState(false);
  const [hasUpperLowerCase, setHasUpperLowerCase] = useState(false);
  const [hasNumber, setHasNumber] = useState(false);
  const [hasSpecialChar, setHasSpecialChar] = useState(false);
  const [emailError, setEmailError] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    console.log("Register attempt:", { email, password });
    setIsLoading(false);
  };

  useEffect(() => {
    const strengthOk = checkPasswordStrength(password);
    setPasswordConfirmed(
      password !== "" && password === reenterPassword && strengthOk,
    );
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
      hasSpecial =
        hasSpecial || "!@#$%^&*()_+-=[]{}|;':\"\\,.<>/?".includes(char);
    }

    setHasUpperLowerCase(hasCapital && hasLower);
    setHasNumber(hasNumber);
    setHasSpecialChar(hasSpecial);

    return hasCapital && hasNumber && hasSpecial && hasLower;
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-100">
      <div className="bg-white p-8 rounded-lg shadow-lg w-96">
        <h1 className="text-2xl font-bold text-center mb-6">Login</h1>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Email
            </label>
            <input
              type="email"
              placeholder="Enter your email"
              value={email}
              style={{ color: "#000000" }}
              onChange={(e) => {
                const v = e.target.value;
                setEmail(v);
                setEmailError(
                  v === "" || validateEmail(v)
                    ? ""
                    : "Please enter a valid email address.",
                );
              }}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
            {emailError ? (
              <p className="text-xs text-red-500 mt-1">{emailError}</p>
            ) : null}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Password
            </label>
            <input
              type="password"
              placeholder="Enter your password"
              value={password}
              style={{ color: "#000000" }}
              onChange={(e) => {
                const v = e.target.value;
                setPassword(v);
                checkPasswordStrength(v);
              }}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>

          <div>
            <label
              className="block text-xs font-medium text-gray-700 mb-1"
              style={{ color: password.length >= 8 ? "green" : "red" }}
            >
              Must be at least 8 characters long
            </label>
            <label
              className="block text-xs font-medium text-gray-700 mb-1"
              style={{ color: hasUpperLowerCase ? "green" : "red" }}
            >
              Must include uppercase and lowercase letters
            </label>
            <label
              className="block text-xs font-medium text-gray-700 mb-1"
              style={{ color: hasNumber ? "green" : "red" }}
            >
              Must include at least one number
            </label>
            <label
              className="block text-xs font-medium text-gray-700 mb-1"
              style={{ color: hasSpecialChar ? "green" : "red" }}
            >
              Must include a special character
            </label>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Confirm Password
            </label>
            <input
              type="password"
              placeholder="Confirm your password"
              value={reenterPassword}
              style={{ color: "#000000" }}
              onChange={(e) => setReenterPassword(e.target.value)}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
            {reenterPassword ? (
              password === reenterPassword ? (
                <p className="text-xs text-green-600 mt-1">Passwords match</p>
              ) : (
                <p className="text-xs text-red-500 mt-1">
                  Passwords do not match
                </p>
              )
            ) : null}
          </div>

          <button
            type="submit"
            disabled={isLoading || !passwordConfirmed}
            className="w-full bg-blue-500 hover:bg-blue-600 text-white font-medium py-2 rounded-lg transition disabled:opacity-50"
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
