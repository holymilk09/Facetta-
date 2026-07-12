export { DEFAULT_API_URL } from './config';

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
      const reason = String(err?.message ?? err);
      return {
        ok: false,
        status: 0,
        body: {
          detail: `Cannot reach Facetta at ${baseUrl}. Check the connection and try again. (${reason})`,
        },
      };
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
    prototypePreview: (spec: unknown) => post('/specs/prototype.svg', spec),
    trueSizePreview: (spec: unknown, instructions = true) =>
      post(`/specs/true-size.svg?instructions=${instructions}`, spec),
    platePreview: (spec: unknown, paper = 'ivory') =>
      post(`/specs/plate.svg?paper=${paper}`, spec),
    fromConcept: (brief: string) =>
      post('/specs/from-concept', { brief, model: 'grok_direct' }),
    renderRequest: (spec: unknown, lighting: string, worn_on: string, style: string) =>
      post('/specs/render-request', { spec, lighting, worn_on, style }),
    createDesign: (created_by: string, spec: unknown, collection?: string) =>
      post('/designs', { created_by, spec, collection: collection || null }),
    createVersion: (designId: string, created_by: string, spec: unknown, collection?: string) =>
      post(`/designs/${designId}/versions`, { created_by, spec, collection: collection || null }),
    listDesigns: () => call('/designs'),
    getDesign: (id: string) => call(`/designs/${id}`),
    getVersionSpec: (id: string, v: number) => call(`/designs/${id}/versions/${v}`),
    getSheet: (id: string, v: number) => call(`/designs/${id}/versions/${v}/sheet.svg`),
    listComments: (id: string, v: number) => call(`/designs/${id}/versions/${v}/comments`),
    listMessages: (id: string) => call(`/designs/${id}/messages`),
    saveStone: (created_by: string, label: string, stone: unknown) =>
      post('/stones', { created_by, label, stone }),
    listStones: (created_by: string) => call(`/stones?created_by=${encodeURIComponent(created_by)}`),
    sendMessage: (id: string, author: string, body: string, author_label?: string) =>
      post(`/designs/${id}/messages`, { author, body, author_label: author_label || null }),
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
