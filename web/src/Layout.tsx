import { NavLink, Outlet } from "react-router-dom";
import { CompanySearch } from "./components/CompanySearch";

const NAV = [
  ["/", "Search"],
  ["/watchlist", "Watchlist"],
  ["/models", "Models"],
  ["/templates", "Templates"],
  ["/reports", "Reports"],
  ["/qa", "Q&A"],
  ["/comps", "Comps"],
  ["/settings", "Settings"],
] as const;

export function Layout() {
  return (
    <div className="app">
      <header>
        <div className="brand">
          <strong>Analekh</strong>
          <span className="muted">The analyst's record, kept for you.</span>
        </div>
        <CompanySearch />
      </header>
      <nav>
        {NAV.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === "/"}>
            {label}
          </NavLink>
        ))}
      </nav>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
