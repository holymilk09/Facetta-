import { StatusBar } from 'expo-status-bar';
import React, { useMemo, useState } from 'react';
import {
  Pressable, SafeAreaView, StyleSheet, Text, TextInput, useWindowDimensions, View,
} from 'react-native';
import { createApi, DEFAULT_API_URL } from './src/api';
import {
  clearSession, hasOnboarded, loadSession, markOnboarded, saveSession, Session,
} from './src/auth';
import { BuilderScreen, EditingTarget } from './src/BuilderScreen';
import { DesignsScreen } from './src/DesignsScreen';
import { LoginScreen } from './src/LoginScreen';
import { OnboardingScreen } from './src/OnboardingScreen';
import { ShareScreen } from './src/ShareScreen';
import { radius, shadows, theme } from './src/theme';

type Tab = 'builder' | 'designs' | 'share';
type Stage = 'onboarding' | 'login' | 'app';

export default function App() {
  const [session, setSession] = useState<Session | null>(() => loadSession());
  const [stage, setStage] = useState<Stage>(() =>
    loadSession() ? 'app' : hasOnboarded() ? 'login' : 'onboarding',
  );
  const [tab, setTab] = useState<Tab>('builder');
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [designer, setDesigner] = useState(session?.designerId ?? 'usr_ana');
  const [editing, setEditing] = useState<EditingTarget | null>(null);
  const [initialSpec, setInitialSpec] = useState<any | null>(null);
  const [focusDesignId, setFocusDesignId] = useState<string | null>(null);
  const [shareToken, setShareToken] = useState<string | null>(null);

  const api = useMemo(() => createApi(apiUrl.replace(/\/$/, '')), [apiUrl]);
  const { width } = useWindowDimensions();
  const isWide = width >= 900; // tablet / desktop: two-pane layouts

  if (stage === 'onboarding') {
    return (
      <SafeAreaView style={styles.root}>
        <StatusBar style="dark" />
        <OnboardingScreen
          onDone={() => {
            markOnboarded();
            setStage('login');
          }}
        />
      </SafeAreaView>
    );
  }

  if (stage === 'login') {
    return (
      <SafeAreaView style={styles.root}>
        <StatusBar style="dark" />
        <LoginScreen
          onSignIn={(s) => {
            saveSession(s);
            setSession(s);
            setDesigner(s.designerId);
            setStage('app');
          }}
        />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="dark" />
      <View style={styles.header}>
        <View style={styles.headerSide} />
        <View style={styles.headerCenter}>
          <Text style={styles.logo}>F A C E T T A</Text>
          <Text style={styles.tagline}>dimensional truth, from dropdowns to factory sheet</Text>
        </View>
        <View style={[styles.headerSide, { alignItems: 'flex-end' }]}>
          {session && (
            <Pressable
              onPress={() => {
                clearSession();
                setSession(null);
                setStage('login');
              }}
              hitSlop={8}>
              <Text style={styles.signOut}>Sign out</Text>
              <Text style={styles.sessionEmail} numberOfLines={1}>
                {session.email}
              </Text>
            </Pressable>
          )}
        </View>
      </View>
      <View style={styles.settings}>
        <TextInput
          style={styles.settingsInput}
          value={apiUrl}
          onChangeText={setApiUrl}
          placeholder="API URL"
          autoCapitalize="none"
        />
        <TextInput
          style={[styles.settingsInput, { flex: 0.5 }]}
          value={designer}
          onChangeText={setDesigner}
          placeholder="designer id"
          autoCapitalize="none"
        />
      </View>
      <View style={styles.tabs}>
        {(['builder', 'designs', 'share'] as Tab[]).map((t) => (
          <Pressable key={t} style={[styles.tab, tab === t && styles.tabActive]} onPress={() => setTab(t)}>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
              {t === 'builder' ? 'Builder' : t === 'designs' ? 'Designs' : 'Share'}
            </Text>
          </Pressable>
        ))}
      </View>

      {tab === 'builder' && (
        <BuilderScreen
          api={api}
          designer={designer}
          editing={editing}
          initialSpec={initialSpec}
          isWide={isWide}
          onSaved={(designId) => {
            setEditing(null);
            setInitialSpec(null);
            setFocusDesignId(designId);
            setTab('designs');
          }}
        />
      )}
      {tab === 'designs' && (
        <DesignsScreen
          api={api}
          designer={designer}
          isWide={isWide}
          focusDesignId={focusDesignId}
          onEdit={(designId, version, spec) => {
            setEditing({ designId, version });
            setInitialSpec(spec);
            setTab('builder');
          }}
          onOpenShare={(token) => {
            setShareToken(token);
            setTab('share');
          }}
        />
      )}
      {tab === 'share' && <ShareScreen api={api} token={shareToken} />}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingTop: 14,
    paddingBottom: 6,
    paddingHorizontal: 12,
  },
  headerSide: { flex: 1 },
  headerCenter: { alignItems: 'center', flex: 2 },
  logo: { fontFamily: theme.serif, fontSize: 20, letterSpacing: 6, color: theme.ink },
  tagline: { fontSize: 11, color: theme.faint, fontStyle: 'italic', marginTop: 2 },
  signOut: { fontSize: 12, color: theme.accent, textAlign: 'right', textDecorationLine: 'underline' },
  sessionEmail: { fontSize: 10, color: theme.faint, textAlign: 'right', marginTop: 2, maxWidth: 140 },
  settings: { flexDirection: 'row', gap: 6, paddingHorizontal: 12, paddingVertical: 6 },
  settingsInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 4,
    fontSize: 12,
    color: theme.faint,
    backgroundColor: theme.card,
  },
  tabs: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: theme.line,
    marginHorizontal: 12,
  },
  tab: { paddingVertical: 8, paddingHorizontal: 16 },
  tabActive: { borderBottomWidth: 2, borderBottomColor: theme.ink },
  tabText: { fontSize: 14, color: theme.faint, fontFamily: theme.serif },
  tabTextActive: { color: theme.ink },
});
