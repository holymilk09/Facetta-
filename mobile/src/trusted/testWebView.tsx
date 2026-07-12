import React from 'react';
import { View, type ViewProps } from 'react-native';

/** Jest-only stand-in; production resolves the native WebView package. */
export function WebView(props: ViewProps & Record<string, unknown>) {
  return <View {...props} testID="factory-sheet-webview" />;
}
