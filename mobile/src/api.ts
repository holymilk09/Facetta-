export const DEFAULT_API_URL =
  process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface ApiResult {
  ok: boolean;
  status: number;
  body: any; // parsed JSON when possible, raw text otherwise (e.g. SVG)
}

export function createApi(baseUrl: string) {
  const call = async (path: string, init?: RequestInit): Promise<ApiResult> => {
    try {
      const res = await fetch(baseUrl + path, {
        headers: { 'Content-Type': 'application/json' },
        ...init,
      });
      const text = await res.text();
      let body: any = text;
      try {
        body = JSON.parse(text);
      } catch {
        // not JSON (SVG responses) — keep raw text
      }
      return { ok: res.ok, status: res.status, body };
    } catch (err: any) {
      return { ok: false, status: 0, body: { detail: String(err?.message ?? err) } };
    }
  };
  const post = (path: string, payload: unknown) =>
    call(path, { method: 'POST', body: JSON.stringify(payload) });

  return {
    baseUrl,
    health: () => call('/health'),
    stones: () => call('/vocabulary/stones'),
    stoneOptions: (id: string) => call(`/vocabulary/stones/${id}/options`),
    findings: () => call('/vocabulary/findings'),
    validateSpec: (spec: unknown) => post('/specs/validate', spec),
    sheetPreview: (spec: unknown) => post('/specs/sheet.svg', spec),
    fromProse: (prose: string, created_by: string) =>
      post('/specs/from-prose', { prose, created_by }),
    createDesign: (created_by: string, spec: unknown) =>
      post('/designs', { created_by, spec }),
    createVersion: (designId: string, created_by: string, spec: unknown) =>
      post(`/designs/${designId}/versions`, { created_by, spec }),
    listDesigns: () => call('/designs'),
    getDesign: (id: string) => call(`/designs/${id}`),
    getVersionSpec: (id: string, v: number) => call(`/designs/${id}/versions/${v}`),
    getSheet: (id: string, v: number) => call(`/designs/${id}/versions/${v}/sheet.svg`),
    listComments: (id: string, v: number) => call(`/designs/${id}/versions/${v}/comments`),
    addComment: (id: string, v: number, comment: unknown) =>
      post(`/designs/${id}/versions/${v}/comments`, comment),
    createShare: (id: string, v: number, scope: 'view' | 'comment') =>
      post(`/designs/${id}/versions/${v}/share`, { scope }),
    openShare: (token: string) => call(`/share/${token}`),
    shareSheet: (token: string) => call(`/share/${token}/sheet.svg`),
    shareComment: (token: string, comment: unknown) =>
      post(`/share/${token}/comments`, comment),
  };
}

export type Api = ReturnType<typeof createApi>;
