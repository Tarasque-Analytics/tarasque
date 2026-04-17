import {
  type RouteConfig,
  route,
  index,
  layout,
} from "@react-router/dev/routes";

export default [
  // Public routes (no auth req)
  index("./routes/navigation.tsx"),

  // Auth routes
  route("login", "./routes/login.tsx"),
  route("register", "./routes/register.tsx"),

  // Protected routes (auth req)
  layout("./layouts/ProtectedLayout.tsx", [
    route("dashboard", "./routes/dashboard.tsx"),
    route("ticker/:symbol", "./routes/ticker.tsx"),
  ]),

  // Wildcard route for 404/unmatched routes
  route("*", "./routes/$.tsx"),
] satisfies RouteConfig;
