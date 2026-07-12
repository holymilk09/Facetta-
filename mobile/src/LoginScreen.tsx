import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator, Animated, Easing, KeyboardAvoidingView, Platform, Pressable,
  ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import {
  requestPasswordReset, Session, signInWithApple, signInWithEmail, signInWithGoogle,
  signUpWithEmail,
} from './auth';
import { StudioCollageBackground } from './StudioCollageBackground';
import { radius, shadows, theme } from './theme';

type Mode = 'signin' | 'signup' | 'forgot';

// U+F8FF renders as the Apple logo on Apple platforms; elsewhere the label stands alone.
const APPLE_GLYPH = Platform.select({ ios: ' ', default: '' });

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

export function LoginScreen({
  onSignIn,
  onShowTour,
}: {
  onSignIn: (session: Session) => void;
  onShowTour?: () => void;
}) {
  const [mode, setMode] = useState<Mode>('signin');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [emailExpanded, setEmailExpanded] = useState(false);
  const [busy, setBusy] = useState<null | 'apple' | 'google' | 'email'>(null);
  const [error, setError] = useState<string | null>(null);
  const [resetSent, setResetSent] = useState(false);

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
  };

  const run = async (kind: 'apple' | 'google' | 'email', task: () => Promise<void>) => {
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
        await requestPasswordReset(email);
        setResetSent(true);
        return;
      }
      const session =
        mode === 'signup'
          ? await signUpWithEmail(name, email, password)
          : await signInWithEmail(email, password);
      onSignIn(session);
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
            <Text style={styles.tagline}>dimensional truth, from dropdowns to factory sheet</Text>
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
              {mode === 'signin'
                ? 'Choose how you would like to continue.'
                : mode === 'signup'
                  ? 'A few details and your drawing table is ready.'
                  : 'Enter your email and we will send a reset link.'}
            </Text>

            {mode !== 'forgot' && (
              <>
                <Pressable
                  style={[styles.socialButton, styles.appleButton, shadows.soft]}
                  disabled={busy !== null}
                  onPress={() => run('apple', async () => onSignIn(await signInWithApple()))}>
                  {busy === 'apple' ? (
                    <ActivityIndicator color={theme.paper} />
                  ) : (
                    <View style={styles.providerRow}>
                      <Text style={styles.appleIcon}>{APPLE_GLYPH.trim()}</Text>
                      <Text style={styles.appleButtonText}>Continue with Apple</Text>
                    </View>
                  )}
                </Pressable>
                <Pressable
                  style={[styles.socialButton, styles.googleButton, shadows.soft]}
                  disabled={busy !== null}
                  onPress={() => run('google', async () => onSignIn(await signInWithGoogle()))}>
                  {busy === 'google' ? (
                    <ActivityIndicator color={theme.ink} />
                  ) : (
                    <View style={styles.googleRow}>
                      <View style={styles.googleBadge}>
                        <Text style={styles.googleBadgeText}>G</Text>
                      </View>
                      <Text style={styles.googleButtonText}>Continue with Google</Text>
                    </View>
                  )}
                </Pressable>
                <Pressable
                  style={[styles.socialButton, styles.emailButton, shadows.soft]}
                  disabled={busy !== null}
                  onPress={() => setEmailExpanded(true)}>
                  <View style={styles.providerRow}>
                    <Text style={styles.emailIcon}>✉</Text>
                    <Text style={styles.emailButtonText}>Continue with email</Text>
                  </View>
                </Pressable>
              </>
            )}

            {(emailExpanded || mode === 'forgot') && mode === 'signup' && (
              <RoundedInput label="Name" value={name} onChange={setName} placeholder="Ana Moreau" />
            )}
            {(emailExpanded || mode === 'forgot') && (
              <>
                <View style={styles.emailFormHeader}>
                  <Text style={styles.emailFormTitle}>Continue with email</Text>
                  {mode !== 'forgot' && (
                    <Pressable onPress={() => setEmailExpanded(false)} hitSlop={8}>
                      <Text style={styles.closeEmail}>Close</Text>
                    </Pressable>
                  )}
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

            {mode === 'signin' && emailExpanded && (
              <Pressable onPress={() => switchMode('forgot')} hitSlop={8} style={styles.forgotLink}>
                <Text style={styles.linkText}>Forgot password?</Text>
              </Pressable>
            )}

            {error && (
              <View style={styles.errorBox}>
                <Text style={styles.errorText}>{error}</Text>
              </View>
            )}
            {resetSent && (
              <View style={styles.okBox}>
                <Text style={styles.okText}>
                  If an account exists for {email.trim()}, a reset link is on its way.
                </Text>
              </View>
            )}

            {(emailExpanded || mode === 'forgot') && (
              <Pressable
                style={[styles.primaryButton, shadows.soft, busy && { opacity: 0.6 }]}
                disabled={busy !== null}
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

            <View style={styles.switchRow}>
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
            </View>
          </Animated.View>

          <Text style={styles.footnote}>Designed for jewelers. Drawn from dimensional truth.</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
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
  socialButton: {
    borderRadius: radius.md,
    paddingVertical: 13,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 10,
  },
  appleButton: { backgroundColor: '#000000' },
  providerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 12 },
  appleIcon: { color: '#ffffff', fontSize: 20, lineHeight: 22 },
  appleButtonText: { color: '#ffffff', fontSize: 15, fontWeight: '500' },
  googleButton: { backgroundColor: theme.card, borderWidth: 1, borderColor: theme.line },
  googleRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  googleBadge: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 1,
    borderColor: theme.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  googleBadgeText: { fontSize: 13, fontWeight: '700', color: '#4285F4' },
  googleButtonText: { color: theme.ink, fontSize: 15, fontWeight: '500' },
  emailButton: { backgroundColor: theme.card, borderWidth: 1, borderColor: theme.line },
  emailIcon: { color: theme.ink, fontSize: 18, lineHeight: 20 },
  emailButtonText: { color: theme.ink, fontSize: 15, fontWeight: '500' },
  emailFormHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 14,
    marginBottom: 14,
  },
  emailFormTitle: { fontFamily: theme.serif, fontSize: 16, color: theme.ink },
  closeEmail: { fontSize: 13, color: theme.accent },
  divider: { flexDirection: 'row', alignItems: 'center', gap: 10, marginVertical: 14 },
  dividerLine: { flex: 1, height: 1, backgroundColor: theme.line },
  dividerText: { fontSize: 12, color: theme.faint },
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
