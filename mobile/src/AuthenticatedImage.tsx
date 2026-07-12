import React, { createContext, useContext } from 'react';
import {
  Image, ImageProps, ImageSourcePropType, StyleSheet, Text, View,
} from 'react-native';
import { theme } from './theme';

type AuthHeaders = Readonly<Record<string, string>> | undefined;

interface AuthenticatedImageContextValue {
  headers: AuthHeaders;
  allowedOrigin: string | null;
}

const AuthenticatedImageHeadersContext = createContext<AuthenticatedImageContextValue>({
  headers: undefined,
  allowedOrigin: null,
});

export function AuthenticatedImageProvider({
  headers, allowedOrigin, children,
}: {
  headers: AuthHeaders;
  allowedOrigin: string;
  children: React.ReactNode;
}) {
  let normalizedOrigin: string | null = null;
  try { normalizedOrigin = new URL(allowedOrigin).origin; } catch { normalizedOrigin = null; }
  return (
    <AuthenticatedImageHeadersContext.Provider value={{ headers, allowedOrigin: normalizedOrigin }}>
      {children}
    </AuthenticatedImageHeadersContext.Provider>
  );
}

function protectedUri(source: ImageSourcePropType | undefined): string | null {
  if (source === undefined || typeof source === 'number' || Array.isArray(source)) return null;
  if (typeof source.uri !== 'string') return null;
  return /^https?:\/\//i.test(source.uri) || source.uri.startsWith('/') ? source.uri : null;
}

/**
 * Every server-emitted remote image is private. Bearer credentials remain in
 * runtime headers; they are never appended to URLs, logs, or persisted state.
 */
export function AuthenticatedImage({
  source, imageRequestHeaders, accessibilityLabel, style, ...props
}: ImageProps & { imageRequestHeaders?: AuthHeaders }) {
  const context = useContext(AuthenticatedImageHeadersContext);
  const headers = imageRequestHeaders ?? context.headers;
  const uri = protectedUri(source);
  const resolvedUri = uri === null ? null : (() => {
    try { return context.allowedOrigin === null ? null : new URL(uri, context.allowedOrigin).toString(); }
    catch { return null; }
  })();
  const sameOrigin = resolvedUri === null ? uri === null : new URL(resolvedUri).origin === context.allowedOrigin;
  if (uri !== null && (!sameOrigin || !headers?.Authorization)) {
    return (
      <View
        accessibilityLabel={`${accessibilityLabel ?? 'Protected image'} unavailable: ${sameOrigin ? 'sign in required' : 'untrusted image origin'}`}
        style={[style, styles.locked]}>
        <Text style={styles.lockedText}>{sameOrigin ? 'Sign in to view this image' : 'Image origin could not be verified'}</Text>
      </View>
    );
  }
  const sourceObject = source !== undefined && typeof source !== 'number' && !Array.isArray(source)
    ? source : null;
  const authenticatedSource = uri === null || sourceObject === null
    ? source
    : {
      ...sourceObject,
      uri: resolvedUri ?? sourceObject.uri,
      headers: { ...(sourceObject.headers ?? {}), ...(headers ?? {}) },
    };
  return <Image {...props} accessibilityLabel={accessibilityLabel} style={style} source={authenticatedSource} />;
}

const styles = StyleSheet.create({
  locked: {
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: theme.line, padding: 12,
  },
  lockedText: { color: theme.faint, fontSize: 12, textAlign: 'center' },
});
