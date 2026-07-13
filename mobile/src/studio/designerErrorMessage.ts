export type DesignerErrorAction =
  | 'create'
  | 'vary'
  | 'refine'
  | 'views'
  | 'present'
  | 'collections'
  | 'activity'
  | 'confirm'
  | 'factory';

export interface DesignerSafeError {
  code?: string;
  category?: string;
  status?: number;
  message?: string;
}

const ACTION_FAILURE: Record<DesignerErrorAction, string> = {
  create: 'Facetta could not create those directions. Try again.',
  vary: 'The variation could not be created. Reopen the design and try again.',
  refine: 'Facetta could not prepare that change. Your saved design is unchanged.',
  views: 'Facetta could not prepare that view. Your saved design is unchanged.',
  present: 'Facetta could not prepare that presentation image. Your design is unchanged.',
  collections: 'Facetta could not open that saved work. Try again.',
  activity: 'Facetta could not update Activity. Try again.',
  confirm: 'Facetta could not review those design suggestions. Nothing was saved.',
  factory: 'Facetta could not prepare the factory review material. Nothing was charged.',
};

/**
 * Server diagnostics stay in telemetry. Designer surfaces receive one useful,
 * provider-neutral explanation and never echo raw identifiers or QA details.
 */
export function designerErrorMessage(
  error: DesignerSafeError,
  action: DesignerErrorAction,
): string {
  const code = (error.code ?? '').toLowerCase();
  const category = (error.category ?? '').toLowerCase();
  if (category === 'authentication' || error.status === 401) {
    return 'Your Facetta session is missing or expired. Sign in again before continuing.';
  }
  if (category === 'authorization' || error.status === 403) {
    return 'This design is not available to the signed-in account.';
  }
  if (code.includes('stale') || error.status === 409) {
    return 'This design changed while you were working. Reopen it before trying again.';
  }
  if (category === 'network' || category === 'unavailable' || error.status === 0) {
    return 'Facetta could not connect. Check your connection and try again.';
  }
  if (category === 'quality') {
    return 'Facetta could not preserve the design well enough. Nothing was saved or charged.';
  }
  if (category === 'validation' || error.status === 422) {
    return 'Check the requested change or reference, then try again.';
  }
  if (category === 'invalid_response') {
    return 'Facetta could not verify the result, so nothing was saved.';
  }
  return ACTION_FAILURE[action];
}
