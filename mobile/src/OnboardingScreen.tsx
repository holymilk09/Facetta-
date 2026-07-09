import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import {
  Float, GemSketch, MotionBackground, Pulse, RingSketch, SparkleSketch,
} from './MotionBackground';
import { radius, shadows, sketchGold, sketchInk, theme } from './theme';

// Grok-rendered vignettes (see facetta.render.generate_image) — photoreal
// jewelry over the pencil construction lines of a factory sheet.
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

function IllustrationSheet() {
  return (
    <View style={styles.vignette}>
      <Float duration={9000} drift={6} tilt={2}>
        <View style={styles.sheet}>
          <View style={styles.sheetRule} />
          <View style={[styles.sheetRule, { width: '55%' }]} />
          <View style={styles.sheetBody}>
            <RingSketch size={54} color={sketchInk(0.5)} stroke={1.5} />
          </View>
          <View style={[styles.sheetRule, { width: '70%' }]} />
        </View>
      </Float>
      <Pulse style={{ position: 'absolute', top: 20, left: 32 }} duration={3000} delay={400}>
        <SparkleSketch size={14} color={sketchGold(0.8)} stroke={2} />
      </Pulse>
    </View>
  );
}

function IllustrationShare() {
  return (
    <View style={styles.vignette}>
      <Float duration={8500} drift={6} tilt={2}>
        <View style={{ width: 150, height: 130 }}>
          <View style={[styles.versionCard, { top: 18, left: 22, opacity: 0.45 }]}>
            <Text style={styles.versionLabel}>v1</Text>
          </View>
          <View style={[styles.versionCard, { top: 0, left: 0 }, shadows.soft]}>
            <Text style={styles.versionLabel}>v2</Text>
            <GemSketch size={40} color={sketchGold(0.8)} stroke={1.5} />
          </View>
          <Pulse style={{ position: 'absolute', top: -8, right: 14 }} duration={2600}>
            <View style={styles.commentDot}>
              <Text style={styles.commentDotText}>2</Text>
            </View>
          </Pulse>
        </View>
      </Float>
    </View>
  );
}

const STEPS = [
  {
    kicker: 'Design',
    title: 'Describe the piece,\nnot the polygons',
    body: "Build a design from a jeweler's vocabulary — stone, cut, color, metal, setting. Structured choices, no CAD, no free-text guesswork.",
    illustration: IllustrationDescribe,
  },
  {
    kicker: 'Precision',
    title: 'Dimensional truth,\nalways',
    body: 'Every output derives from exact millimeters. Carat and size are cross-checked by stone density, so an impossible spec is caught before anyone cuts metal.',
    illustration: IllustrationTruth,
  },
  {
    kicker: 'Manufacture',
    title: 'Factory-ready sheets\nin one tap',
    body: 'Your parameters compile into an annotated technical sheet any workshop can build from — the same drawing, every time, from the same spec.',
    illustration: IllustrationSheet,
  },
  {
    kicker: 'Collaborate',
    title: 'Every version,\non the record',
    body: 'Designs are immutable versions with share links and pinned comments. Designer, factory, and client always reference the same unambiguous state.',
    illustration: IllustrationShare,
  },
];

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
  const last = step === STEPS.length - 1;
  const { kicker, title, body, illustration: Illustration } = STEPS[step];

  return (
    <View style={styles.root}>
      <MotionBackground intensity={0.8} />

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
        <Dots count={STEPS.length} active={step} />
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
    backgroundColor: theme.card,
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
  sheet: {
    width: 130,
    height: 160,
    borderRadius: radius.sm,
    borderWidth: 1.5,
    borderColor: sketchInk(0.45),
    backgroundColor: theme.card,
    padding: 12,
    gap: 8,
  },
  sheetRule: { height: 2, width: '80%', borderRadius: 1, backgroundColor: sketchInk(0.25) },
  sheetBody: { flex: 1, alignItems: 'center', justifyContent: 'center' },
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
