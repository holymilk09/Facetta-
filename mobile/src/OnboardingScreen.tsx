import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import {
  Float, Pulse, RingSketch, SparkleSketch,
} from './MotionBackground';
import { StudioCollageBackground } from './StudioCollageBackground';
import { radius, shadows, sketchGold, sketchInk, theme } from './theme';

// Product vignettes used to introduce the designer journey. The UI copy must
// stay provider-neutral and must not imply production authority.
const ringRender = require('../assets/onboarding-ring.jpg');
const gemRender = require('../assets/onboarding-gem.jpg');

// ---------------------------------------------------------------------------
// Step illustrations — rendered vignettes and line-art built from primitives.
// ---------------------------------------------------------------------------

function IllustrationDescribe() {
  return (
    <View style={styles.vignette}>
      <Float duration={8000} drift={5} tilt={1.5}>
        <View style={[styles.renderFrame, shadows.soft]}>
          <Image source={ringRender} style={styles.renderImage} resizeMode="cover" />
        </View>
      </Float>
      <Pulse style={{ position: 'absolute', top: 6, right: 12 }} duration={2600}>
        <SparkleSketch size={18} color={sketchGold(0.9)} stroke={2} />
      </Pulse>
      <Pulse style={{ position: 'absolute', bottom: 10, left: 8 }} duration={3400} delay={700}>
        <SparkleSketch size={12} color={sketchGold(0.7)} stroke={2} />
      </Pulse>
    </View>
  );
}

function IllustrationTruth() {
  return (
    <View style={styles.vignette}>
      <Float duration={9000} drift={4} tilt={1.5}>
        <View style={[styles.renderFrame, shadows.soft]}>
          <Image source={gemRender} style={styles.renderImageShort} resizeMode="cover" />
        </View>
      </Float>
      {/* dimension callout: |--- 6.5 mm ---| */}
      <View style={styles.dimension}>
        <View style={styles.dimensionTick} />
        <View style={styles.dimensionLine} />
        <Text style={styles.dimensionLabel}>6.5 mm</Text>
        <View style={styles.dimensionLine} />
        <View style={styles.dimensionTick} />
      </View>
    </View>
  );
}

function IllustrationLibrary() {
  return (
    <View style={styles.vignette}>
      <Float duration={9000} drift={6} tilt={2}>
        <View style={styles.libraryStack}>
          <View style={styles.libraryCardBack} />
          <View style={styles.libraryCard}>
            <RingSketch size={54} color={sketchInk(0.5)} stroke={1.5} />
            <View style={styles.libraryCopy}>
              <View style={styles.sheetRule} />
              <View style={[styles.sheetRule, { width: '65%' }]} />
            </View>
          </View>
        </View>
      </Float>
      <Pulse style={{ position: 'absolute', top: 20, left: 32 }} duration={3000} delay={400}>
        <SparkleSketch size={14} color={sketchGold(0.8)} stroke={2} />
      </Pulse>
    </View>
  );
}

export const ONBOARDING_STEPS = [
  {
    kicker: 'Create',
    title: 'Begin from your idea',
    body: 'Start with a sentence, drawing, photograph, render, or master-geometry reference. Facetta gives you one to four visual directions to consider.',
    illustration: IllustrationDescribe,
  },
  {
    kicker: 'Choose & refine',
    title: 'Choose before you refine',
    body: 'Choose and preserve a direction first. Precision refinement appears for revisions with confirmed design facts, and every change stays a preview until you apply it.',
    illustration: IllustrationTruth,
  },
  {
    kicker: 'Preserve',
    title: 'Keep every useful direction',
    body: 'Organize design families, variations, and immutable revisions. Prepare client or marketing material anytime; factory review stays optional and appears only when a revision is eligible.',
    illustration: IllustrationLibrary,
  },
] as const;

/** Fades + slides its children in on mount; re-keyed per step for transitions. */
function StepReveal({ children }: { children: React.ReactNode }) {
  const t = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(t, {
      toValue: 1,
      duration: 420,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [t]);
  return (
    <Animated.View
      style={{
        flex: 1,
        opacity: t,
        transform: [{ translateY: t.interpolate({ inputRange: [0, 1], outputRange: [24, 0] }) }],
      }}>
      {children}
    </Animated.View>
  );
}

function Dots({ count, active }: { count: number; active: number }) {
  return (
    <View style={styles.dots}>
      {Array.from({ length: count }, (_, i) => (
        <View key={i} style={[styles.dot, i === active && styles.dotActive]} />
      ))}
    </View>
  );
}

export function OnboardingScreen({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const last = step === ONBOARDING_STEPS.length - 1;
  const { kicker, title, body, illustration: Illustration } = ONBOARDING_STEPS[step];

  return (
    <View style={styles.root}>
      <StudioCollageBackground />

      <View style={styles.topBar}>
        <Text style={styles.wordmark}>F A C E T T A</Text>
        {!last && (
          <Pressable onPress={onDone} hitSlop={12}>
            <Text style={styles.skip}>Skip</Text>
          </Pressable>
        )}
      </View>

      <StepReveal key={step}>
        <View style={styles.content}>
          <View style={[styles.illustrationCard, shadows.lifted]}>
            <Illustration />
          </View>
          <Text style={styles.kicker}>{kicker}</Text>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.body}>{body}</Text>
        </View>
      </StepReveal>

      <View style={styles.footer}>
        <Dots count={ONBOARDING_STEPS.length} active={step} />
        <Pressable
          style={[styles.cta, shadows.soft]}
          onPress={() => (last ? onDone() : setStep(step + 1))}>
          <Text style={styles.ctaText}>{last ? 'Get started' : 'Continue'}</Text>
        </Pressable>
        {step > 0 && (
          <Pressable onPress={() => setStep(step - 1)} hitSlop={12}>
            <Text style={styles.back}>Back</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingTop: 18,
  },
  wordmark: { fontFamily: theme.serif, fontSize: 15, letterSpacing: 5, color: theme.ink },
  skip: { fontSize: 14, color: theme.faint },
  content: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 32 },
  illustrationCard: {
    width: 240,
    height: 220,
    borderRadius: radius.xl,
    backgroundColor: 'rgba(255,255,255,0.9)',
    borderWidth: 1,
    borderColor: theme.line,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 32,
  },
  vignette: { width: 200, height: 180, alignItems: 'center', justifyContent: 'center' },
  renderFrame: { borderRadius: radius.lg, backgroundColor: theme.card },
  renderImage: { width: 172, height: 172, borderRadius: radius.lg },
  renderImageShort: { width: 172, height: 138, borderRadius: radius.lg },
  kicker: {
    fontSize: 12,
    letterSpacing: 3,
    textTransform: 'uppercase',
    color: theme.gold,
    marginBottom: 10,
  },
  title: {
    fontFamily: theme.serif,
    fontSize: 27,
    lineHeight: 34,
    color: theme.ink,
    textAlign: 'center',
    marginBottom: 14,
  },
  body: {
    fontSize: 15,
    lineHeight: 23,
    color: theme.faint,
    textAlign: 'center',
    maxWidth: 340,
  },
  footer: { alignItems: 'center', paddingBottom: 34, paddingHorizontal: 32 },
  dots: { flexDirection: 'row', gap: 7, marginBottom: 22 },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: theme.line,
  },
  dotActive: { backgroundColor: theme.gold, width: 22 },
  cta: {
    backgroundColor: theme.ink,
    borderRadius: radius.pill,
    paddingVertical: 15,
    paddingHorizontal: 20,
    alignItems: 'center',
    alignSelf: 'stretch',
    maxWidth: 420,
    width: '100%',
  },
  ctaText: { color: theme.paper, fontSize: 15, letterSpacing: 1 },
  back: { marginTop: 14, fontSize: 14, color: theme.faint },

  // illustration details
  dimension: { flexDirection: 'row', alignItems: 'center', marginTop: 18, gap: 6 },
  dimensionLine: { width: 30, height: 1, backgroundColor: sketchInk(0.4) },
  dimensionTick: { width: 1, height: 10, backgroundColor: sketchInk(0.4) },
  dimensionLabel: { fontSize: 11, color: theme.ink, fontFamily: theme.serif },
  libraryStack: { width: 166, height: 150, justifyContent: 'center', alignItems: 'center' },
  libraryCardBack: {
    position: 'absolute', width: 138, height: 124, borderRadius: radius.md,
    backgroundColor: theme.goldSoft, borderWidth: 1, borderColor: theme.line,
    transform: [{ translateX: 11 }, { translateY: -9 }, { rotate: '4deg' }],
  },
  libraryCard: {
    width: 148, height: 132, borderRadius: radius.md, backgroundColor: 'rgba(255,255,255,0.96)',
    borderWidth: 1, borderColor: theme.line, padding: 14, alignItems: 'center',
    justifyContent: 'center', gap: 11,
  },
  libraryCopy: { width: '100%', gap: 6 },
  sheetRule: { height: 2, width: '80%', borderRadius: 1, backgroundColor: sketchInk(0.25) },
  versionCard: {
    position: 'absolute',
    width: 110,
    height: 110,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: sketchInk(0.35),
    backgroundColor: theme.card,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  versionLabel: { fontSize: 11, color: theme.faint, fontFamily: theme.serif },
  commentDot: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: theme.gold,
    alignItems: 'center',
    justifyContent: 'center',
  },
  commentDotText: { color: theme.paper, fontSize: 12, fontWeight: '600' },
});
