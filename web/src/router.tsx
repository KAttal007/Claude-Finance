import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter } from "react-router-dom";
import { Layout } from "./Layout";
import { Placeholder } from "./pages/Placeholder";
import { SearchPage } from "./pages/SearchPage";

// Heavy screens (AG Grid, ECharts) load on demand.
const Watchlist = lazy(() => import("./pages/Watchlist").then((m) => ({ default: m.Watchlist })));
const CompanyPage = lazy(() =>
  import("./pages/CompanyPage").then((m) => ({ default: m.CompanyPage })),
);
const ChangeSetReview = lazy(() =>
  import("./pages/ChangeSetReview").then((m) => ({ default: m.ChangeSetReview })),
);
const AssumptionReview = lazy(() =>
  import("./pages/AssumptionReview").then((m) => ({ default: m.AssumptionReview })),
);
const Models = lazy(() => import("./pages/Models").then((m) => ({ default: m.Models })));
const Templates = lazy(() => import("./pages/Templates").then((m) => ({ default: m.Templates })));

const page = (el: ReactNode) => <Suspense fallback={<p>Loading…</p>}>{el}</Suspense>;

// Screens from design doc 19.1. Reports, Q&A, Comps and Settings land in Phases 4-5.
export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <SearchPage /> },
      { path: "watchlist", element: page(<Watchlist />) },
      { path: "companies/:symbol", element: page(<CompanyPage />) },
      { path: "change-sets/:id", element: page(<ChangeSetReview />) },
      { path: "models", element: page(<Models />) },
      { path: "models/:id/assumptions", element: page(<AssumptionReview />) },
      { path: "templates", element: page(<Templates />) },
      { path: "reports", element: <Placeholder title="Reports" phase={4} /> },
      { path: "qa", element: <Placeholder title="Q&A" phase={4} /> },
      { path: "comps", element: <Placeholder title="Comps builder" phase={5} /> },
      { path: "settings", element: <Placeholder title="Settings" phase={5} /> },
    ],
  },
]);
