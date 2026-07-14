import React, {
  createContext,
  useEffect,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Image,
  ImageProps,
  ImageSourcePropType,
  ImageURISource,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
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

const MAX_WEB_IMAGE_ATTEMPTS = 3;
const SAFE_IMAGE_ERROR = 'Image could not be loaded.';

type WebImageStatus = 'loading' | 'ready' | 'error';

interface WebImageState {
  requestKey: string;
  status: WebImageStatus;
  objectUrl: string | null;
  attempts: number;
}

function safeImageErrorEvent(): Parameters<NonNullable<ImageProps['onError']>>[0] {
  return { nativeEvent: { error: SAFE_IMAGE_ERROR } } as Parameters<NonNullable<ImageProps['onError']>>[0];
}

function WebAuthenticatedImage({
  sourceObject,
  resolvedUri,
  requestHeaders,
  accessibilityLabel,
  style,
  onError,
  ...props
}: Omit<ImageProps, 'source'> & {
  sourceObject: ImageURISource;
  resolvedUri: string;
  requestHeaders: Readonly<Record<string, string>>;
}) {
  const headerEntries = Object.entries(requestHeaders)
    .sort(([first], [second]) => first.localeCompare(second));
  const headersKey = JSON.stringify(headerEntries);
  const stableHeaders = useMemo(
    () => Object.fromEntries(headerEntries),
    // The serialized entries are intentionally used only as an internal request identity.
    // They are never rendered, logged, or included in an error.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [headersKey],
  );
  const requestKey = `${resolvedUri}\n${headersKey}`;
  const [retryVersion, setRetryVersion] = useState(0);
  const [state, setState] = useState<WebImageState>({
    requestKey,
    status: 'loading',
    objectUrl: null,
    attempts: 0,
  });
  const requestSequence = useRef(0);
  const objectUrlRef = useRef<string | null>(null);
  const attemptsRef = useRef({ requestKey, count: 0 });
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const revokeCurrentObjectUrl = (): void => {
    const current = objectUrlRef.current;
    if (current === null) return;
    objectUrlRef.current = null;
    if (typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(current);
  };

  useEffect(() => {
    if (attemptsRef.current.requestKey !== requestKey) {
      attemptsRef.current = { requestKey, count: 0 };
    }

    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    const controller = typeof AbortController === 'undefined' ? null : new AbortController();
    let active = true;
    revokeCurrentObjectUrl();
    setState({
      requestKey,
      status: 'loading',
      objectUrl: null,
      attempts: attemptsRef.current.count,
    });

    const failSafely = (): void => {
      if (!active || requestSequence.current !== sequence) return;
      attemptsRef.current.count += 1;
      setState({
        requestKey,
        status: 'error',
        objectUrl: null,
        attempts: attemptsRef.current.count,
      });
      onErrorRef.current?.(safeImageErrorEvent());
    };

    void (async () => {
      try {
        const response = await fetch(resolvedUri, {
          headers: stableHeaders,
          signal: controller?.signal,
        });
        if (!active || requestSequence.current !== sequence) return;
        const contentType = response.headers.get('content-type')
          ?.split(';', 1)[0]
          .trim()
          .toLowerCase();
        if (!response.ok || contentType === undefined || !contentType.startsWith('image/')) {
          failSafely();
          return;
        }

        const blob = await response.blob();
        if (!active || requestSequence.current !== sequence) return;
        if (blob.size <= 0 || typeof URL.createObjectURL !== 'function') {
          failSafely();
          return;
        }

        const objectUrl = URL.createObjectURL(blob);
        if (!active || requestSequence.current !== sequence) {
          if (typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(objectUrl);
          return;
        }
        objectUrlRef.current = objectUrl;
        setState({
          requestKey,
          status: 'ready',
          objectUrl,
          attempts: attemptsRef.current.count,
        });
      } catch {
        failSafely();
      }
    })();

    return () => {
      active = false;
      requestSequence.current += 1;
      controller?.abort();
      revokeCurrentObjectUrl();
    };
  }, [headersKey, requestKey, resolvedUri, retryVersion, stableHeaders]);

  const safeLabel = accessibilityLabel ?? 'Protected image';
  const currentState = state.requestKey === requestKey
    ? state
    : { requestKey, status: 'loading' as const, objectUrl: null, attempts: 0 };

  if (currentState.status === 'loading') {
    return (
      <View
        accessibilityLabel={`${safeLabel} loading`}
        accessibilityRole="image"
        style={[style, styles.locked]}>
        <Text style={styles.lockedText}>Loading image…</Text>
      </View>
    );
  }

  if (currentState.status === 'error' || currentState.objectUrl === null) {
    const canRetry = currentState.attempts < MAX_WEB_IMAGE_ATTEMPTS;
    return (
      <View
        accessibilityLabel={`${safeLabel} unavailable: image could not be loaded`}
        accessibilityRole="image"
        style={[style, styles.locked]}>
        <Text style={styles.lockedText}>Image could not be loaded</Text>
        {canRetry ? (
          <Pressable
            accessibilityLabel={`${safeLabel} retry`}
            accessibilityRole="button"
            onPress={() => setRetryVersion((current) => current + 1)}
            style={styles.retryButton}>
            <Text style={styles.retryButtonText}>Retry image</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  const {
    body: _body,
    headers: _headers,
    method: _method,
    uri: _uri,
    ...displaySourceProperties
  } = sourceObject;
  const displaySource: ImageURISource = {
    ...displaySourceProperties,
    uri: currentState.objectUrl,
  };

  return (
    <Image
      {...props}
      accessibilityLabel={accessibilityLabel}
      onError={() => {
        requestSequence.current += 1;
        revokeCurrentObjectUrl();
        attemptsRef.current.count += 1;
        setState({
          requestKey,
          status: 'error',
          objectUrl: null,
          attempts: attemptsRef.current.count,
        });
        onErrorRef.current?.(safeImageErrorEvent());
      }}
      source={displaySource}
      style={style}
    />
  );
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
  if (Platform.OS === 'web' && uri !== null && resolvedUri !== null && sourceObject !== null && headers) {
    return (
      <WebAuthenticatedImage
        {...props}
        accessibilityLabel={accessibilityLabel}
        requestHeaders={{ ...(sourceObject.headers ?? {}), ...headers }}
        resolvedUri={resolvedUri}
        sourceObject={sourceObject}
        style={style}
      />
    );
  }
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
  retryButton: {
    borderColor: theme.faint,
    borderRadius: 999,
    borderWidth: 1,
    marginTop: 10,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  retryButtonText: { color: theme.ink, fontSize: 11, fontWeight: '700' },
});
