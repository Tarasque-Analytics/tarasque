import {
  type RouteConfig,
  route,
  index,
  layout,
} from "@react-router/dev/routes";

export default [
  // Public routes (no auth req)
  index("routes/home.tsx"),

  // Auth routes
  layout(".layouts/AuthLayout.tsx", [
    route("login", "routes/login.tsx"),
    route("register", "routes/register.tsx"),
  ]),

  // Protected routes (auth req)
  layout(".layouts/ProtectedLayout.tsx", [
    route("dashboard", "routes/dashboard.tsx"),
    //  Ticker routes with shared layout
    layout(".layouts/TickerLayout.tsx", [
      route("ticker/:symbol", "routes/ticker.tsx"),
    ]),
  ]),

  // Wildcard route for 404/unmatched routes
  route("*", "routes/$.tsx"),
] satisfies RouteConfig;
