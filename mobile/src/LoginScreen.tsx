import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator, Animated, Easing, KeyboardAvoidingView, Platform, Pressable,
  ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import {
  requestPasswordReset, Session, signInWithEmail, signUpWithEmail, updatePassword,
} from './auth';
import { supabaseConfigurationError } from './supabase';
import { StudioCollageBackground } from './StudioCollageBackground';
import { radius, shadows, theme } from './theme';

type Mode = 'signin' | 'signup' | 'forgot';

function RoundedInput(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  secure?: boolean;
  email?: boolean;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <View style={styles.inputBlock}>
      <Text style={styles.inputLabel}>{props.label}</Text>
      <TextInput
        style={[styles.input, focused && styles.inputFocused]}
        value={props.value}
        onChangeText={props.onChange}
        placeholder={props.placeholder}
        placeholderTextColor={theme.faint}
        secureTextEntry={props.secure}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType={props.email ? 'email-address' : 'default'}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      />
    </View>
  );
}

export function PasswordRecoveryScreen({ onComplete }: { onComplete: () => void }) {
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    if (busy) return;
    if (password !== confirmation) {
      setError('Passwords do not match.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updatePassword(password);
      onComplete();
    } catch (reason: any) {
      setError(String(reason?.message ?? 'Facetta could not update the password. Try again.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={styles.recoveryRoot}>
      <View style={[styles.card, shadows.floating]}>
        <Text style={styles.cardTitle}>Choose a new password</Text>
        <Text style={styles.cardSubtitle}>Use at least 8 characters.</Text>
        <RoundedInput label="New password" value={password} onChange={setPassword} placeholder="New password" secure />
        <RoundedInput label="Confirm password" value={confirmation} onChange={setConfirmation} placeholder="Confirm password" secure />
        {error !== null && <View style={styles.errorBox}><Text style={styles.errorText}>{error}</Text></View>}
        <Pressable style={styles.primaryButton} disabled={busy} onPress={() => { void submit(); }}>
          {busy ? <ActivityIndicator color={theme.paper} /> : <Text style={styles.primaryButtonText}>Update password</Text>}
        </Pressable>
      </View>
    </View>
  );
}

export function LoginScreen({
  onSignIn,
  onShowTour,
  localPreviewSignIn,
  authService = { requestPasswordReset, signInWithEmail, signUpWithEmail },
  configurationError = supabaseConfigurationError,
}: {
  onSignIn: (session: Session) => void;
  onShowTour?: () => void;
  localPreviewSignIn?: () => Promise<Session>;
  authService?: Pick<typeof import('./auth'), 'requestPasswordReset' | 'signInWithEmail' | 'signUpWithEmail'>;
  configurationError?: string | null;
}) {
  const [mode, setMode] = useState<Mode>('signin');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [emailExpanded, setEmailExpanded] = useState(true);
  const [busy, setBusy] = useState<null | 'email' | 'local-preview'>(null);
  const [error, setError] = useState<string | null>(null);
  const [resetSent, setResetSent] = useState(false);
  const [confirmationEmail, setConfirmationEmail] = useState<string | null>(null);

  // Card entrance: rise + fade, like a sheet placed on the drawing table.
  const entrance = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(entrance, {
      toValue: 1,
      duration: 560,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [entrance]);

  const switchMode = (m: Mode) => {
    setMode(m);
    setEmailExpanded(m === 'forgot' ? true : emailExpanded);
    setError(null);
    setResetSent(false);
    setConfirmationEmail(null);
  };

  const run = async (kind: 'email' | 'local-preview', task: () => Promise<void>) => {
    if (busy) return;
    setBusy(kind);
    setError(null);
    try {
      await task();
    } catch (err: any) {
      setError(String(err?.message ?? err));
    } finally {
      setBusy(null);
    }
  };

  const submitEmail = () =>
    run('email', async () => {
      if (mode === 'forgot') {
        await authService.requestPasswordReset(email);
        setResetSent(true);
        return;
      }
      if (mode === 'signup') {
        const result = await authService.signUpWithEmail(name, email, password);
        if (result.kind === 'confirmation_required') {
          setConfirmationEmail(result.email);
          return;
        }
        onSignIn(result.session);
        return;
      }
      onSignIn(await authService.signInWithEmail(email, password));
    });
  const localPreviewOnly = localPreviewSignIn !== undefined
    && configurationError !== null && mode === 'signin';
  const submitLocalPreview = () => localPreviewSignIn === undefined
    ? undefined
    : run('local-preview', async () => {
      onSignIn(await localPreviewSignIn());
    });

  return (
    <View style={styles.root}>
      <StudioCollageBackground />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}>
          <View style={styles.brand}>
            <Text style={styles.wordmark}>F A C E T T A</Text>
            <Text style={styles.tagline}>Create quickly. Refine without losing the design.</Text>
            {onShowTour && (
              <Pressable onPress={onShowTour} hitSlop={8} style={styles.tourLink}>
                <Text style={styles.tourLinkText}>See how it works →</Text>
              </Pressable>
            )}
          </View>

          <Animated.View
            style={[
              styles.card,
              shadows.floating,
              {
                opacity: entrance,
                transform: [
                  { translateY: entrance.interpolate({ inputRange: [0, 1], outputRange: [36, 0] }) },
                ],
              },
            ]}>
            <Text style={styles.cardTitle}>
              {mode === 'signin' ? 'Continue to Facetta' : mode === 'signup' ? 'Create your studio' : 'Reset password'}
            </Text>
            <Text style={styles.cardSubtitle}>
              {localPreviewOnly
                ? 'Open this localhost Studio without creating an account.'
                : mode === 'signin'
                ? 'Sign in with your studio email.'
                : mode === 'signup'
                  ? 'A few details and your drawing table is ready.'
                  : 'Enter your email and we will send a reset link.'}
            </Text>

            {localPreviewOnly && (
              <View style={styles.localPreviewBlock}>
                <Text style={styles.localPreviewTitle}>Local development preview</Text>
                <Text style={styles.localPreviewBody}>
                  Uses a temporary session from the API running on this Mac. It is not a production account.
                </Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Open local Studio preview"
                  testID="local-preview-sign-in"
                  style={[styles.primaryButton, shadows.soft, busy && { opacity: 0.6 }]}
                  disabled={busy !== null}
                  onPress={() => { void submitLocalPreview(); }}>
                  {busy === 'local-preview' ? (
                    <ActivityIndicator color={theme.paper} />
                  ) : (
                    <Text style={styles.primaryButtonText}>Open local Studio</Text>
                  )}
                </Pressable>
              </View>
            )}

            {!localPreviewOnly && (emailExpanded || mode === 'forgot') && mode === 'signup' && (
              <RoundedInput label="Name" value={name} onChange={setName} placeholder="Ana Moreau" />
            )}
            {!localPreviewOnly && (emailExpanded || mode === 'forgot') && (
              <>
                <View style={styles.emailFormHeader}>
                  <Text style={styles.emailFormTitle}>Continue with email</Text>
                </View>
                <RoundedInput
                  label="Email"
                  value={email}
                  onChange={setEmail}
                  placeholder="you@studio.com"
                  email
                />
                {mode !== 'forgot' && (
                  <RoundedInput
                    label="Password"
                    value={password}
                    onChange={setPassword}
                    placeholder="At least 8 characters"
                    secure
                  />
                )}
              </>
            )}

            {!localPreviewOnly && mode === 'signin' && emailExpanded && (
              <Pressable onPress={() => switchMode('forgot')} hitSlop={8} style={styles.forgotLink}>
                <Text style={styles.linkText}>Forgot password?</Text>
              </Pressable>
            )}

            {error && (
              <View style={styles.errorBox}>
                <Text style={styles.errorText}>{error}</Text>
              </View>
            )}
            {configurationError !== null && !localPreviewOnly && (
              <View style={styles.errorBox}>
                <Text style={styles.errorText}>{configurationError}</Text>
              </View>
            )}
            {confirmationEmail !== null && (
              <View style={styles.okBox}>
                <Text style={styles.okText}>
                  Check {confirmationEmail} to confirm your account, then return here to sign in.
                </Text>
              </View>
            )}
            {resetSent && (
              <View style={styles.okBox}>
                <Text style={styles.okText}>
                  If an account exists for {email.trim()}, a reset link is on its way.
                </Text>
              </View>
            )}

            {!localPreviewOnly && (emailExpanded || mode === 'forgot') && (
              <Pressable
                style={[styles.primaryButton, shadows.soft, (busy || configurationError) && { opacity: 0.6 }]}
                disabled={busy !== null || configurationError !== null}
                onPress={submitEmail}>
                {busy === 'email' ? (
                  <ActivityIndicator color={theme.paper} />
                ) : (
                  <Text style={styles.primaryButtonText}>
                    {mode === 'signin' ? 'Sign in' : mode === 'signup' ? 'Create account' : 'Send reset link'}
                  </Text>
                )}
              </Pressable>
            )}

            {!localPreviewOnly && <View style={styles.switchRow}>
              {mode === 'signin' ? (
                <>
                  <Text style={styles.switchText}>New to Facetta? </Text>
                  <Pressable onPress={() => switchMode('signup')} hitSlop={8}>
                    <Text style={styles.linkText}>Create an account</Text>
                  </Pressable>
                </>
              ) : (
                <>
                  <Text style={styles.switchText}>
                    {mode === 'signup' ? 'Already have an account? ' : 'Remembered it? '}
                  </Text>
                  <Pressable onPress={() => switchMode('signin')} hitSlop={8}>
                    <Text style={styles.linkText}>Sign in</Text>
                  </Pressable>
                </>
              )}
            </View>}
          </Animated.View>

          <Text style={styles.footnote}>Designed for jewelers. Drawn from dimensional truth.</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  recoveryRoot: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: theme.paper },
  scroll: { flexGrow: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  brand: {
    alignItems: 'center',
    marginBottom: 26,
    paddingHorizontal: 18,
    paddingVertical: 12,
    borderRadius: radius.lg,
    backgroundColor: 'rgba(253,253,250,0.68)',
  },
  wordmark: { fontFamily: theme.serif, fontSize: 26, letterSpacing: 8, color: theme.ink },
  tagline: { fontSize: 12, color: theme.faint, fontStyle: 'italic', marginTop: 6 },
  tourLink: { marginTop: 12 },
  tourLinkText: { fontSize: 13, color: theme.accent, textDecorationLine: 'underline' },
  card: {
    width: '100%',
    maxWidth: 440,
    backgroundColor: 'rgba(255,255,255,0.88)',
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: theme.line,
    padding: 26,
  },
  cardTitle: { fontFamily: theme.serif, fontSize: 22, color: theme.ink, marginBottom: 4 },
  cardSubtitle: { fontSize: 13, color: theme.faint, marginBottom: 20 },
  localPreviewBlock: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.md,
    padding: 14,
    backgroundColor: theme.paper,
  },
  localPreviewTitle: { fontSize: 15, fontWeight: '700', color: theme.ink },
  localPreviewBody: { fontSize: 12, lineHeight: 18, color: theme.faint, marginTop: 5 },
  emailFormHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 14,
    marginBottom: 14,
  },
  emailFormTitle: { fontFamily: theme.serif, fontSize: 16, color: theme.ink },
  inputBlock: { marginBottom: 12 },
  inputLabel: { fontSize: 12, color: theme.faint, marginBottom: 5, letterSpacing: 0.4 },
  input: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: theme.ink,
    backgroundColor: theme.paper,
  },
  inputFocused: { borderColor: theme.gold, backgroundColor: theme.card },
  forgotLink: { alignSelf: 'flex-end', marginBottom: 4 },
  linkText: { fontSize: 13, color: theme.accent, textDecorationLine: 'underline' },
  errorBox: {
    borderWidth: 1,
    borderColor: theme.danger,
    borderRadius: radius.sm,
    padding: 10,
    marginTop: 6,
    backgroundColor: 'rgba(160,48,48,0.05)',
  },
  errorText: { color: theme.danger, fontSize: 13 },
  okBox: {
    borderWidth: 1,
    borderColor: theme.ok,
    borderRadius: radius.sm,
    padding: 10,
    marginTop: 6,
    backgroundColor: 'rgba(59,110,70,0.06)',
  },
  okText: { color: theme.ok, fontSize: 13 },
  primaryButton: {
    backgroundColor: theme.ink,
    borderRadius: radius.pill,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 12,
  },
  primaryButtonText: { color: theme.paper, fontSize: 15, letterSpacing: 0.6 },
  switchRow: { flexDirection: 'row', justifyContent: 'center', marginTop: 16 },
  switchText: { fontSize: 13, color: theme.faint },
  footnote: { marginTop: 24, fontSize: 12, color: theme.faint, fontStyle: 'italic' },
});
