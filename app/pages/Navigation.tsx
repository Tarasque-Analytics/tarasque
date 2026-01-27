import { Link } from "react-router";
import "./navigation.css";

export default function Navigation() {
  return (
    <div className="navigation-container">
      <h1>Navigation Page</h1>
      <p>
        Volarbear is a go. Use the links below to navigate the site for testing
        purposes.
      </p>
      <nav>
        <ul className="nav-list">
          <li className="nav-item">
            <Link to="/login" className="nav-link">
              Login
            </Link>
          </li>
          <li className="nav-item">
            <Link to="/register" className="nav-link">
              Register
            </Link>
          </li>
          <li className="nav-item">
            <Link to="/dashboard" className="nav-link">
              Dashboard
            </Link>
          </li>
          <li className="nav-item">
            <Link to="/ticker/AAPL" className="nav-link">
              Ticker (AAPL Example)
            </Link>
          </li>
          <li className="nav-item">
            <Link to="/asdfghjkl" className="nav-link">
              404 Page
            </Link>
          </li>
        </ul>
      </nav>
    </div>
  );
}
