import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Template } from "../api/client";

// Template onboarding (design doc 14): upload, review suggested mapping, test build, activate.
export function Templates() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const [symbol, setSymbol] = useState("");
  const upload = useMutation({
    mutationFn: (form: FormData) => api.uploadTemplate(form),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["templates"] }),
  });
  const test = useMutation({ mutationFn: (t: Template) => api.testTemplate(t.id, symbol) });
  const activate = useMutation({
    mutationFn: (t: Template) => api.activateTemplate(t.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["templates"] }),
  });

  return (
    <section>
      <h2>Templates</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          upload.mutate(new FormData(e.currentTarget));
        }}
      >
        <input name="workbook" type="file" accept=".xlsx,.xlsm" required />
        <input name="name" placeholder="Template name" required />
        <input name="sectors" placeholder="Sectors, comma separated" required />
        <label>
          <input name="from_existing_model" type="checkbox" value="true" /> existing model
        </label>
        <button type="submit">Upload</button>
        {upload.isError && <span className="error">{String(upload.error)}</span>}
      </form>
      <p>
        Test company:{" "}
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
      </p>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Version</th>
            <th>Sectors</th>
            <th>Owner</th>
            <th>Status</th>
            <th>Mapped rows</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.map((t) => {
            const rows = (t.mapping?.rows as { confidence: number }[] | undefined) ?? [];
            const low = rows.filter((r) => r.confidence < 0.8).length;
            return (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>{t.version}</td>
                <td>{t.sectors.join(", ")}</td>
                <td>{t.owner}</td>
                <td>{t.status}</td>
                <td>
                  {rows.length} {low > 0 && <span className="warn">({low} to review)</span>}
                </td>
                <td>
                  <button onClick={() => test.mutate(t)} disabled={!symbol}>
                    Test build
                  </button>
                  <button onClick={() => activate.mutate(t)} disabled={t.status === "active"}>
                    Activate
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {test.data && <pre>{JSON.stringify(test.data, null, 2)}</pre>}
    </section>
  );
}
