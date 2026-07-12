import React, { useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { Button, Notice } from '../components';
import { theme } from '../theme';
import type { TrustedApiClient } from './client';
import type { DraftFactorySheetPreview as Preview, JsonObject } from './types';

type PreviewClient = Pick<TrustedApiClient, 'previewDraftFactorySheet'>;

export interface DraftFactorySheetPreviewProps {
  spec: JsonObject;
  client: PreviewClient;
}

const sheetHtml = (svg: string): string => `<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      html, body { margin: 0; padding: 0; background: #fdfdfa; }
      svg { display: block; width: 100%; height: auto; }
    </style>
  </head>
  <body>${svg}</body>
</html>`;

/** Provider-free preview of the exact draft facts through the canonical sheet renderer. */
export function DraftFactorySheetPreview({
  spec,
  client,
}: DraftFactorySheetPreviewProps) {
  const currentFingerprint = useMemo(() => JSON.stringify(spec), [spec]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewFingerprint, setPreviewFingerprint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stale = preview !== null && previewFingerprint !== currentFingerprint;

  const load = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    const result = await client.previewDraftFactorySheet(spec);
    setBusy(false);
    if (result.error !== null) {
      setError(result.error.message);
      return;
    }
    setPreview(result.data);
    setPreviewFingerprint(currentFingerprint);
  };

  const preliminary = preview?.authority === 'preliminary_not_for_production';

  return (
    <View style={styles.wrap}>
      <Text style={styles.heading}>Dimensional-diagram preview</Text>
      <Text style={styles.copy}>
        Render the current factory facts as a schematic review diagram. It
        exposes estimated, confirmed, and unresolved information, but generic
        template geometry is not a production drawing.
      </Text>
      {error !== null && <Notice kind="error" text={error} />}
      {stale && (
        <Notice
          kind="info"
          text="Factory facts changed after this diagram. Refresh before reviewing it."
        />
      )}
      <Button
        title={busy
          ? 'Rendering dimensional diagram…'
          : preview === null ? 'Preview dimensional diagram' : 'Refresh dimensional diagram'}
        kind="ghost"
        disabled={busy}
        onPress={() => void load()}
      />
      {preview !== null && (
        <>
          <Notice
            kind={preliminary ? 'error' : 'ok'}
            text={preliminary
              ? 'Preliminary specification review — not for production. Resolve the blockers printed on the diagram before factory review.'
              : 'Spec-derived dimensional diagram. Confirmed facts may be authoritative; its circles, outlines, and template geometry never become production geometry.'}
          />
          <View style={[styles.sheet, stale && styles.sheetStale]}>
            <WebView
              accessibilityLabel="Dimensional diagram preview"
              originWhitelist={['*']}
              source={{ html: sheetHtml(preview.svg) }}
              scrollEnabled
              style={styles.webview}
            />
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: 12,
    marginBottom: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: theme.line,
  },
  heading: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 15,
    marginBottom: 5,
  },
  copy: { color: theme.faint, fontSize: 12, lineHeight: 17, marginBottom: 8 },
  sheet: {
    height: 560,
    overflow: 'hidden',
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: 10,
    backgroundColor: theme.paper,
  },
  sheetStale: { opacity: 0.45 },
  webview: { flex: 1, backgroundColor: theme.paper },
});
