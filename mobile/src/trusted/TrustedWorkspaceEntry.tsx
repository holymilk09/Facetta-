import React, { useMemo } from 'react';

import { createTrustedApiClient } from './client';
import { TrustedWorkflowScreen } from './TrustedWorkflowScreen';

export interface TrustedWorkspaceEntryProps {
  apiBaseUrl: string;
  designer: string;
  initialProjectId?: string | null;
  enabled?: boolean;
  viewportWidth?: number;
  getAccessToken?: () => string | null | Promise<string | null>;
  onOpenAdvancedSpecifications?: (designId: string, version: number) => void;
}

/**
 * Stable integration seam for the parallel redesign.
 *
 * The redesign owns navigation, composition, and visual presentation. This
 * component owns only trusted API construction and forwards the exact workflow
 * state machine. App-level code therefore never needs provider names, raw
 * model controls, image-run internals, or duplicate request contracts.
 */
export function TrustedWorkspaceEntry({
  apiBaseUrl,
  designer,
  initialProjectId = null,
  enabled,
  viewportWidth,
  getAccessToken,
  onOpenAdvancedSpecifications,
}: TrustedWorkspaceEntryProps) {
  const baseUrl = apiBaseUrl.replace(/\/$/, '');
  const api = useMemo(() => createTrustedApiClient({
    baseUrl,
    ...(getAccessToken === undefined ? {} : { getAccessToken }),
  }), [baseUrl, getAccessToken]);

  return (
    <TrustedWorkflowScreen
      api={api}
      designer={designer}
      initialProjectId={initialProjectId}
      enabled={enabled}
      viewportWidth={viewportWidth}
      onOpenAdvancedSpecifications={onOpenAdvancedSpecifications}
    />
  );
}
