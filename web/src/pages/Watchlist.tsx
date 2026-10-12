import { useQuery } from "@tanstack/react-query";
import { AllCommunityModule, type ColDef, ModuleRegistry } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { Link } from "react-router-dom";
import { api, type WatchlistEntry } from "../api/client";

ModuleRegistry.registerModules([AllCommunityModule]);

const columns: ColDef<WatchlistEntry>[] = [
  {
    field: "symbol",
    cellRenderer: (p: { value: string }) => <Link to={`/companies/${p.value}`}>{p.value}</Link>,
  },
  { field: "name", flex: 1 },
  { field: "last_filing", headerName: "Last filing" },
  {
    field: "validation_blocked",
    headerName: "Validation",
    valueFormatter: (p) => (p.value ? "blocked" : "ok"),
  },
  { field: "pending_change_sets", headerName: "Pending change sets" },
];

export function Watchlist() {
  const { data = [], isLoading } = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  return (
    <section>
      <h2>Watchlist</h2>
      {isLoading ? (
        <p>Loading…</p>
      ) : data.length === 0 ? (
        <p className="muted">Nothing watched yet. Open a company and add it.</p>
      ) : (
        <div className="grid">
          <AgGridReact rowData={data} columnDefs={columns} domLayout="autoHeight" />
        </div>
      )}
    </section>
  );
}
