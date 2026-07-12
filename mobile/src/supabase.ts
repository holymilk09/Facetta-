import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient, processLock, type SupabaseClient } from '@supabase/supabase-js';
import * as SecureStore from 'expo-secure-store';
import { AppState, Linking, Platform } from 'react-native';
import 'react-native-url-polyfill/auto';

const SECURE_CHUNK_SIZE = 1800;
const secureOptions = {
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
};

type SecureSlot = 'a' | 'b';
type SecureManifest = { slot: SecureSlot; chunks: number };

const secureKey = (key: string, slot: SecureSlot, index: number) =>
  `${key}.${slot}.${index}`;

async function readSecureManifest(key: string): Promise<SecureManifest | null> {
  const raw = await SecureStore.getItemAsync(`${key}.meta`, secureOptions);
  if (raw === null) return null;
  try {
    const value = JSON.parse(raw);
    if ((value.slot === 'a' || value.slot === 'b')
      && Number.isInteger(value.chunks) && value.chunks > 0) return value;
  } catch {
    // Corrupt secure storage fails closed as no session.
  }
  return null;
}

const nativeSecureStorage = {
  async getItem(key: string): Promise<string | null> {
    const manifest = await readSecureManifest(key);
    if (manifest === null) {
      // One-time compatibility read for the earlier single-value adapter.
      return SecureStore.getItemAsync(key, secureOptions);
    }
    const chunks = await Promise.all(Array.from(
      { length: manifest.chunks },
      (_, index) => SecureStore.getItemAsync(
        secureKey(key, manifest.slot, index), secureOptions,
      ),
    ));
    return chunks.some((chunk) => chunk === null) ? null : chunks.join('');
  },
  async setItem(key: string, value: string): Promise<void> {
    const previous = await readSecureManifest(key);
    const slot: SecureSlot = previous?.slot === 'a' ? 'b' : 'a';
    const chunks = value.match(new RegExp(`.{1,${SECURE_CHUNK_SIZE}}`, 'gs')) ?? [''];
    await Promise.all(chunks.map((chunk, index) => SecureStore.setItemAsync(
      secureKey(key, slot, index), chunk, secureOptions,
    )));
    await SecureStore.setItemAsync(
      `${key}.meta`, JSON.stringify({ slot, chunks: chunks.length }), secureOptions,
    );
    if (previous !== null) {
      await Promise.all(Array.from({ length: previous.chunks }, (_, index) =>
        SecureStore.deleteItemAsync(secureKey(key, previous.slot, index), secureOptions)));
    }
    await SecureStore.deleteItemAsync(key, secureOptions);
  },
  async removeItem(key: string): Promise<void> {
    const manifest = await readSecureManifest(key);
    if (manifest !== null) {
      await Promise.all(Array.from({ length: manifest.chunks }, (_, index) =>
        SecureStore.deleteItemAsync(secureKey(key, manifest.slot, index), secureOptions)));
    }
    await Promise.all([
      SecureStore.deleteItemAsync(`${key}.meta`, secureOptions),
      SecureStore.deleteItemAsync(key, secureOptions),
    ]);
  },
};

const url = process.env.EXPO_PUBLIC_SUPABASE_URL?.trim() ?? '';
const publishableKey = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim() ?? '';

function validUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'https:' || parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

export const supabaseConfigurationError = !validUrl(url) || publishableKey.length === 0
  ? 'Email sign-in is not configured for this build. Contact the Facetta team.'
  : null;

let client: SupabaseClient | null = null;
let appStateListenerInstalled = false;
let linkingListenerInstalled = false;

async function acceptNativeAuthLink(authClient: SupabaseClient, link: string | null): Promise<void> {
  if (link === null || Platform.OS === 'web') return;
  try {
    const parsed = new URL(link);
    if (parsed.protocol !== 'facetta:' || parsed.hostname !== 'auth') return;
    const code = parsed.searchParams.get('code');
    if (code !== null && code.length > 0) await authClient.auth.exchangeCodeForSession(code);
  } catch {
    // Invalid or unrelated deep links are ignored without logging their contents.
  }
}

export function getSupabaseClient(): SupabaseClient | null {
  if (supabaseConfigurationError !== null) return null;
  if (client === null) {
    client = createClient(url, publishableKey, {
      auth: {
        storage: Platform.OS === 'web' ? AsyncStorage : nativeSecureStorage,
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: Platform.OS === 'web',
        lock: processLock,
        flowType: 'pkce',
      },
    });
  }
  if (Platform.OS !== 'web' && !appStateListenerInstalled) {
    appStateListenerInstalled = true;
    AppState.addEventListener('change', (state) => {
      if (state === 'active') client?.auth.startAutoRefresh();
      else client?.auth.stopAutoRefresh();
    });
  }
  if (Platform.OS !== 'web' && !linkingListenerInstalled) {
    linkingListenerInstalled = true;
    void Linking.getInitialURL().then((link) => acceptNativeAuthLink(client!, link));
    Linking.addEventListener('url', ({ url: link }) => { void acceptNativeAuthLink(client!, link); });
  }
  return client;
}

export function passwordResetRedirectUrl(): string {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    return `${window.location.origin}/auth/reset-password`;
  }
  return 'facetta://auth/reset-password';
}
