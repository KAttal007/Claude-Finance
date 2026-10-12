// Typed API client. Types come from the FastAPI OpenAPI schema (npm run api-types), so the
// front end and back end cannot drift (design doc Appendix G.5).
import type { components } from "./schema";

export type Schemas = components["schemas"];
export type SearchHit = Schemas["SearchHitOut"];
export type CompanyDetail = Schemas["CompanyDetail"];
export type WatchlistEntry = Schemas["WatchlistEntryOut"];
export type Filing = Schemas["FilingOut"];
export type Fact = Schemas["FactOut"];
export type ChangeSet = Schemas["ChangeSetOut"];
export type ChangeItem = Schemas["ChangeItemOut"];
export type Template = Schemas["TemplateOut"];
export type Assumption = Schemas["AssumptionOut"];
export type ModelOut = Schemas["ModelOut"];
export type BuildOut = Schemas["BuildOut"];

const BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> =
    init.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  const res = await fetch(BASE + path, { headers, ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  search: (q: string) => call<SearchHit[]>(`/companies/search?q=${encodeURIComponent(q)}`),
  company: (symbol: string) => call<CompanyDetail>(`/companies/${symbol}`),
  filings: (symbol: string) => call<Filing[]>(`/companies/${symbol}/filings`),
  facts: (symbol: string, elements: string) =>
    call<Fact[]>(`/companies/${symbol}/facts?elements=${encodeURIComponent(elements)}`),
  watchlist: () => call<WatchlistEntry[]>("/watchlist"),
  watch: (symbol: string) => post<CompanyDetail>("/watchlist", { symbol }),
  unwatch: (symbol: string) => call<void>(`/watchlist/${symbol}`, { method: "DELETE" }),
  analyse: (symbol: string) => post<Schemas["JobOut"]>(`/companies/${symbol}/analyse`),
  refresh: (symbol: string) => post<Schemas["JobOut"]>(`/companies/${symbol}/refresh`),
  startCoverage: (symbol: string, templateId?: number) =>
    post<BuildOut>("/coverage", { symbol, template_id: templateId ?? null }),
  assumptions: (modelId: number) => call<Assumption[]>(`/models/${modelId}/assumptions`),
  decideAssumptions: (modelId: number, body: Schemas["AssumptionDecisions"]) =>
    post<Assumption[]>(`/models/${modelId}/assumptions/decisions`, body),
  finalize: (modelId: number) => post<Record<string, unknown>>(`/models/${modelId}/finalize`),
  models: () => call<ModelOut[]>("/models"),
  changeSet: (id: number) => call<ChangeSet>(`/change-sets/${id}`),
  decide: (id: number, body: Schemas["Decisions"]) =>
    post<ChangeSet>(`/change-sets/${id}/decisions`, body),
  apply: (id: number) => post<Record<string, unknown>>(`/change-sets/${id}/apply`),
  templates: () => call<Template[]>("/templates"),
  uploadTemplate: (form: FormData) => call<Template>("/templates", { method: "POST", body: form }),
  testTemplate: (id: number, symbol: string) =>
    post<Schemas["TemplateTestOut"]>(`/templates/${id}/test`, { symbol }),
  activateTemplate: (id: number) => post<Template>(`/templates/${id}/activate`),
};
