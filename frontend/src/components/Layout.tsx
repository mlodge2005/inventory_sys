import { FormEvent, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

const LINKS = [
  ["/dashboard", "Home"],
  ["/inventory", "Parts"],
  ["/drawers", "Drawers"],
  ["/alerts", "Alerts"],
  ["/transactions", "History"],
  ["/import", "Import"],
  ["/settings", "Settings"],
];

export function Layout({ children, title }: { children: React.ReactNode; title: string }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  function onSearch(event: FormEvent) {
    event.preventDefault();
    navigate(`/inventory?search=${encodeURIComponent(query.trim())}`);
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <header className="topbar">
        <NavLink className="brand" to="/dashboard">
          {title}
        </NavLink>
        <form className="top-search" onSubmit={onSearch}>
          <input
            aria-label="Search inventory"
            placeholder="Search parts"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit">Search</button>
        </form>
      </header>
      <div className="app-body">
        <nav className="side-nav" aria-label="Primary">
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to}>
              {label}
            </NavLink>
          ))}
        </nav>
        <main className="page" id="content">
          {children}
        </main>
      </div>
      <nav className="bottom-nav" aria-label="Mobile">
        <NavLink to="/dashboard">Home</NavLink>
        <NavLink to="/inventory">Parts</NavLink>
        <NavLink to="/drawers">Drawers</NavLink>
        <NavLink to="/alerts">Alerts</NavLink>
        <NavLink to="/settings">More</NavLink>
      </nav>
    </div>
  );
}
