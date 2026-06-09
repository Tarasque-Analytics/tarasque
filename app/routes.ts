import { type RouteConfig, route, index, layout } from "@react-router/dev/routes";

export default [
  // Public routes (no auth req)
  index("./routes/navigation.tsx"),

  // Auth routes
  route("login", "./routes/login.tsx"),
  route("register", "./routes/register.tsx"),

  // Protected routes (auth req) - make sure to run backend when testing
  layout("./layouts/ProtectedLayout.tsx", [
    route("dashboard", "./routes/dashboard.tsx"),
    route("equity", "./routes/equity.tsx"),
    route("equity/:symbol", "./routes/ticker.tsx"),
    route("macro", "./routes/macro.tsx"),
    route("sector", "./routes/sector_landing.tsx"),
    route("sector/:sector", "./routes/sector.tsx"),
    route("model", "./routes/model_landing.tsx"),
    route("model/:symbol", "./routes/model.tsx"),
  ]),

  // Wildcard route for 404/unmatched routes
  route("*", "./routes/$.tsx"),
] satisfies RouteConfig;
