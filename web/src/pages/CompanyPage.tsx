import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";

const REVENUE = "RevenueFromOperations";

export function CompanyPage() {
  const { symbol = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const company = useQuery({ queryKey: ["company", symbol], queryFn: () => api.company(symbol) });
  const filings = useQuery({ queryKey: ["filings", symbol], queryFn: () => api.filings(symbol) });
  const revenue = useQuery({
    queryKey: ["facts", symbol, REVENUE],
    queryFn: () => api.facts(symbol, REVENUE),
  });
  const watch = useMutation({
    mutationFn: async () => {
      if (company.data?.watched) await api.unwatch(symbol);
      else await api.watch(symbol);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["company", symbol] }),
  });
  const analyse = useMutation({ mutationFn: () => api.analyse(symbol) });
  const start = useMutation({
    mutationFn: () => api.startCoverage(symbol),
    onSuccess: (b) => navigate(`/models/${b.model.id}/assumptions`),
  });

  if (company.isError) return <p className="error">{String(company.error)}</p>;
  if (!company.data) return <p>Loading…</p>;
  const c = company.data;
  const quarters = (revenue.data ?? [])
    .filter((f) => f.period_start && f.consolidated)
    .sort((a, b) => a.period_end.localeCompare(b.period_end));

  return (
    <section>
      <h2>
        {c.name} <small className="muted">{c.nse_symbol}</small>
      </h2>
      <p className="muted">
        {c.sector ?? "Sector not classified"} · coverage: {c.coverage_level}
        {c.results_taxonomy ? ` · ${c.results_taxonomy}` : ""}
      </p>
      <div className="actions">
        <button onClick={() => watch.mutate()}>
          {c.watched ? "Remove from watchlist" : "Add to watchlist"}
        </button>
        <button onClick={() => analyse.mutate()} disabled={analyse.isPending}>
          Analyse
        </button>
        <button onClick={() => start.mutate()} disabled={start.isPending}>
          Start coverage
        </button>
        {analyse.data && <span className="muted">job {analyse.data.status}</span>}
        {start.isError && <span className="error">{String(start.error)}</span>}
      </div>

      {quarters.length > 1 && (
        <ReactECharts
          style={{ height: 260 }}
          option={{
            tooltip: { trigger: "axis" },
            xAxis: { type: "category", data: quarters.map((f) => f.period_end) },
            yAxis: { type: "value", name: "INR crore" },
            series: [
              {
                name: "Revenue",
                type: "bar",
                data: quarters.map((f) => Number(f.value ?? 0) / 1e7),
              },
            ],
          }}
        />
      )}

      <h3>Filings</h3>
      <table>
        <thead>
          <tr>
            <th>Period end</th>
            <th>Kind</th>
            <th>Basis</th>
            <th>Status</th>
            <th>Checks</th>
          </tr>
        </thead>
        <tbody>
          {(filings.data ?? []).map((f) => (
            <tr key={f.id}>
              <td>{f.period_end ?? "-"}</td>
              <td>{f.kind}</td>
              <td>
                {f.consolidated == null ? "-" : f.consolidated ? "Consolidated" : "Standalone"}
              </td>
              <td>{f.status}</td>
              <td>{f.meta?.blocks_auto_apply ? "blocked" : "ok"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
