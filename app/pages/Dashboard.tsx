import { Link } from "react-router";

export default function Dashboard() {
  return (
    <div>
      <h1>Dashboard</h1>
      <p>Dashboard content here.</p>
      <Link to="/">Go home</Link>
    </div>
  );
}
