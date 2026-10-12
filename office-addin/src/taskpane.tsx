import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

// Phase 5 task pane (design doc 13.3, 19.2): works on the open workbook directly, reads the
// hidden tag (custom document properties) so no lookup is needed, shows the pending change set
// and highlights each item's cell when clicked. Writes still go through the approval gate.
const API = localStorage.getItem("analekh_api") ?? "http://localhost:8000";

type Item = { id: number; kind: string; sheet: string; cell: string; new_value: string | null };

async function readTag(): Promise<{ modelId?: string; symbol?: string }> {
  return Excel.run(async (ctx) => {
    const props = ctx.workbook.properties.custom;
    props.load("items/key,items/value");
    await ctx.sync();
    const get = (k: string) => props.items.find((p) => p.key === k)?.value as string | undefined;
    return { modelId: get("analekh_model_id"), symbol: get("analekh_symbol") };
  });
}

async function select(sheet: string, cell: string) {
  await Excel.run(async (ctx) => {
    ctx.workbook.worksheets.getItem(sheet).getRange(cell).select();
    await ctx.sync();
  });
}

function TaskPane() {
  const [tag, setTag] = useState<{ modelId?: string; symbol?: string }>({});
  const [csId, setCsId] = useState("");
  const [items, setItems] = useState<Item[]>([]);

  useEffect(() => {
    readTag().then(setTag).catch(() => setTag({}));
  }, []);

  const load = async () => {
    const res = await fetch(`${API}/change-sets/${csId}`);
    setItems((await res.json()).items);
  };

  return (
    <main style={{ fontFamily: "Segoe UI, sans-serif", padding: 12 }}>
      <h3>Analekh</h3>
      <p>{tag.symbol ? `Linked to ${tag.symbol}` : "This workbook is not linked yet."}</p>
      <input value={csId} onChange={(e) => setCsId(e.target.value)} placeholder="change set id" />
      <button onClick={load} disabled={!csId}>
        Load
      </button>
      <ul>
        {items.map((i) => (
          <li key={i.id} onClick={() => select(i.sheet, i.cell)} style={{ cursor: "pointer" }}>
            {i.kind} {i.sheet}!{i.cell} → {i.new_value ?? ""}
          </li>
        ))}
      </ul>
    </main>
  );
}

Office.onReady(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <TaskPane />
    </StrictMode>,
  );
});
