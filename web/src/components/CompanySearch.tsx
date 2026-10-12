import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

// Autocomplete over every NSE company (design doc F2): symbol prefix first, then fuzzy name.
export function CompanySearch() {
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const { data = [] } = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.search(q),
    enabled: q.trim().length >= 2,
  });
  const open = (symbol: string) => {
    setQ("");
    navigate(`/companies/${symbol}`);
  };
  return (
    <div className="search">
      <input
        aria-label="Search companies"
        placeholder="Search any NSE company"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && data[0] && open(data[0].nse_symbol)}
      />
      {q.trim().length >= 2 && data.length > 0 && (
        <ul className="suggestions" role="listbox">
          {data.map((h) => (
            <li key={h.id} role="option" aria-selected={false} onClick={() => open(h.nse_symbol)}>
              <strong>{h.nse_symbol}</strong> {h.name}
              {h.sector && <span className="muted"> · {h.sector}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
