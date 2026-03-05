# Planned Tech Stack
  ## Framework
    React 19
    React Router 7
    Typescript 5
    Vite 7
  ## Frontend
    TailwindCSS 4
    Google Fonts
    Chart.js 4
    React Chart.js 2
  ## Backend
    Task: Set up FastAPI for data requests
    Task: Set up PostgreSQL for holding model outputs
  ## Server-Side Rendering
    Node.js server
  ## Deployment
    Task: Deploy initial site on Vercel
    Later: Migrate to AWS Amplify
  ## CI/CD
    Task: Create github workflow to trigger on PR
      npm ci
      npm run lint
      npm run typecheck
      Vitest
      npm run build
    Task: Set up Vitest for unit testing
    Task: Set up Playwright for web testing
  ## QA & Monitoring
    (?)
  ## Security
    Optional (for resume): Rate limiting
    Optional (for resume): Configurable domain access

# IMPORTANT:
Both the frontend and the backend need to be running (see the related instructions for the [frontend](#frontend-development) and the [backend](#backend-quick-start)) in order to load any page that requires dynamic data.

# Volarbmodel Application Developer Guide (AI Generated)

## Overview
The volarbmodel web application is a full-stack TypeScript application for visualizing and interacting with volatility arbitrage model data. This guide covers the application/frontend portion of the project.

## Tech Stack

### Core Framework
- **React 19** - UI library
- **React Router 7** - Full-stack framework with file-based routing
- **TypeScript 5** - Type-safe development
- **Vite 7** - Build tool and dev server

### Styling
- **Tailwind CSS 4** - Utility-first CSS framework
- **Custom CSS** - Global styles in `app/app.css`
- **Google Fonts** - Inter font family

### Data Visualization
- **Chart.js 4.5** - Charting library
- **react-chartjs-2** - React wrapper for Chart.js

### Server-Side Rendering
- **SSR enabled** - Server-side rendering by default via React Router
- **@react-router/node** - Node.js adapter
- **@react-router/serve** - Production server

## Prerequisites
- **Node.js 22.21.1** (specified in README)
- npm or yarn package manager

## Project Structure

```
volarbmodel/
├── app/                          # Application source code
│   ├── routes/                   # Route components
│   │   ├── navigation.tsx        # Home/landing page (index)
│   │   ├── login.tsx             # Login route
│   │   ├── register.tsx          # Registration route
│   │   ├── dashboard.tsx         # Main dashboard (protected)
│   │   ├── ticker.tsx            # Ticker detail page (protected)
│   │   └── $.tsx                 # 404 catch-all route
│   ├── layouts/                  # Layout wrappers
│   │   ├── AuthLayout.tsx        # Wrapper for login/register
│   │   └── ProtectedLayout.tsx   # Wrapper for authenticated routes
│   ├── pages/                    # Page-level components
│   │   ├── Navigation.tsx
│   │   ├── Login.tsx
│   │   ├── Register.tsx
│   │   ├── Dashboard.tsx
│   │   ├── Ticker.tsx
│   │   └── NotFound.tsx
│   ├── components/               # Reusable components
│   │   ├── dashboard/            # Dashboard-specific components
│   │   ├── ticker/               # Ticker page components
│   │   └── ui/                   # Generic UI components
│   ├── context/                  # React Context providers
│   │   └── TickerDataContext.tsx # Ticker data state management
│   ├── assets/                   # Static assets
│   ├── root.tsx                  # Root component & layout
│   ├── routes.ts                 # Route configuration
│   └── app.css                   # Global styles
├── build/                        # Build output
│   ├── client/                   # Client bundle
│   └── server/                   # Server bundle
├── public/                       # Static public assets
├── vite.config.ts                # Vite configuration
├── react-router.config.ts        # React Router config
├── tsconfig.json                 # TypeScript config
└── package.json                  # Dependencies & scripts
```

## Getting Started

### Installation
```bash
npm install
```

### Frontend Development
```bash
npm run dev
```
Starts the development server with hot module replacement.

### Build
```bash
npm run build
```
Creates production builds for both client and server.

### Production Server
```bash
npm start
```
Serves the production build.

### Type Checking
```bash
npm run typecheck
```
Generates types and runs TypeScript compiler checks.

## Routing Architecture

The application uses React Router 7's file-based routing with a configuration-based approach defined in `app/routes.ts`.

### Route Structure

**Public Routes:**
- `/` - Landing/navigation page (no authentication)

**Auth Routes (AuthLayout):**
- `/login` - User login
- `/register` - User registration

**Protected Routes (ProtectedLayout):**
- `/dashboard` - Main dashboard view
- `/ticker/:symbol` - Individual ticker analysis page with dynamic symbol parameter

**Catch-all:**
- `*` - 404 Not Found page

### Layout System

The app uses nested layouts for route organization:

- **AuthLayout** - Wraps unauthenticated routes (login/register), likely handles redirect logic if already authenticated
- **ProtectedLayout** - Wraps authenticated routes, handles authentication guards and redirects

## State Management

### Context API
The app uses React Context for state management:

- **TickerDataContext** - Manages ticker-related data and state across the ticker detail page and related components

### Future Considerations
As the app grows, you may want to consider:
- Additional contexts for user authentication state
- Global app state management
- Data fetching/caching strategies (React Query, SWR, etc.)

## Styling Approach

### Tailwind CSS
The app primarily uses Tailwind CSS utility classes for styling. Tailwind v4 is integrated via the Vite plugin.

### Custom CSS
Global styles and custom CSS are defined in `app/app.css`, which is imported in `root.tsx`.

### Component-Specific Styles
Some pages have their own CSS modules (e.g., `navigation.css`).

## Data Visualization

The application uses Chart.js with the React wrapper `react-chartjs-2` for rendering financial charts and volatility data visualizations.

Common use cases:
- Time series charts for volatility
- Comparative analysis charts
- Factor correlation visualizations

## Server-Side Rendering (SSR)

The app is configured with SSR enabled by default (`ssr: true` in `react-router.config.ts`).

**Benefits:**
- Improved initial page load performance
- Better SEO
- Faster time-to-interactive

**Considerations:**
- Ensure code that relies on browser APIs (window, document) only runs on the client
- Use React Router's `useIsomorphicLayoutEffect` or check for `typeof window !== 'undefined'`

## TypeScript Configuration

The project uses TypeScript with strict type checking. Key features:
- Path aliases configured via `vite-tsconfig-paths`
- React Router auto-generates route types (`npm run typecheck`)
- Type definitions for React 19 and React Router 7

## Development Tips

### Adding a New Route
1. Create the route component in `app/routes/`
2. Create the corresponding page component in `app/pages/`
3. Add route configuration in `app/routes.ts`
4. For protected routes, nest under `ProtectedLayout`

### Adding a New Component
- Reusable UI components → `app/components/ui/`
- Feature-specific components → `app/components/{feature}/`
- Follow TypeScript conventions for props typing

### Working with Tailwind
- Use Tailwind utility classes for most styling
- Extract repeated patterns into components
- Use `@apply` in CSS files sparingly for complex patterns

### Data Fetching
React Router 7 supports loaders and actions:
- Use `loader` exports for server-side data fetching
- Use `action` exports for form submissions and mutations
- Access loaded data via `useLoaderData()` hook

## Contributing Guidelines

1. **Code Style**: Follow existing TypeScript and React conventions
2. **Type Safety**: Ensure all components and functions are properly typed
3. **Component Structure**: Keep components focused and single-responsibility
4. **Naming**: Use descriptive names for components, files, and variables
5. **Testing**: (Add testing framework as needed - consider Vitest)

## Common Issues & Solutions

### Port Already in Use
If the dev server can't start, another process may be using the port. Kill the process or change the port in Vite config.

### Type Errors After Route Changes
Run `npm run typecheck` to regenerate route types after modifying `routes.ts`.

### SSR Hydration Mismatches
Ensure server and client render the same content. Avoid using `Date.now()`, `Math.random()`, or browser-only APIs without guards.

## Backend Setup

The application includes a FastAPI backend server for serving ticker data. For detailed setup instructions, see [BACKEND_SETUP.md](BACKEND_SETUP.md).

### Backend Quick Start

1. **Install backend dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```

2. **Start the backend server**:
   ```bash
   python backend/main.py
   ```
   The server will run on `http://localhost:8000`

3. **In a separate terminal, start the frontend**:
   ```bash
   npm run dev
   ```

### API Integration

The frontend communicates with the backend through the API utility in `app/utils/tickers.ts`:

- `getAvailableTickers()` - Fetches list of available ticker symbols
- `loadTickerPayload(symbol)` - Loads ticker data for a specific symbol

### Database Integration (TODO)

The backend is designed to easily integrate with PostgreSQL. See the [BACKEND_SETUP.md](BACKEND_SETUP.md) file for PostgreSQL integration instructions.

## Next Steps for New Developers

1. **Explore the codebase**: Start with `app/routes.ts` and trace through the route structure
2. **Run the dev server**: Get the app running locally and navigate through the routes
3. **Run the backend**: Start the FastAPI server to serve ticker data
4. **Review components**: Check out the components in `app/components/` to understand the UI building blocks
5. **Understand data flow**: Review `TickerDataContext.tsx` to see how data is managed
6. **Read React Router docs**: Familiarize yourself with React Router 7 features (loaders, actions, etc.)
7. **Check Chart.js docs**: If working on visualizations, review Chart.js and react-chartjs-2 documentation

## Useful Resources

- [React Router 7 Documentation](https://reactrouter.com)
- [Tailwind CSS v4 Documentation](https://tailwindcss.com)
- [Chart.js Documentation](https://www.chartjs.org)
- [Vite Documentation](https://vitejs.dev)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)

---

**Note**: This guide focuses on the application/frontend architecture. For information about the ML models and financial analysis logic, refer to the `model/` directory documentation.
