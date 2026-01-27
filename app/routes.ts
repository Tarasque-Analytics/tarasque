import { type RouteConfig, route, index } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("dashboard", "routes/dashboard.tsx"),
  route("login", "routes/login.tsx"),
  route("ticker/:symbol", "routes/ticker.tsx"),

  // leave wildcard route last to handle unmatched routes
  route("*", "routes/$.tsx"),
] satisfies RouteConfig;