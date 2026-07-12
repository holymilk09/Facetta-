import React, { useEffect, useState } from 'react';
import { Animated, Easing, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { MotionBackground } from './MotionBackground';
import { radius, shadows, theme } from './theme';

// Real screenshots of the running app (captured live via Playwright against a
// seeded local backend — see the PR description for how) plus one Grok
// photoreal hero for the render step. Not mockups: the actual UI, cropped.
const promptShot = require('../assets/tour-prompt.jpg');
const adjustShot = require('../assets/tour-adjust.jpg');
const dimsShot = require('../assets/tour-dims.jpg');
const sheetShot = require('../assets/tour-sheet.jpg');
const renderShot = require('../assets/tour-render.jpg');
const libraryShot = require('../assets/tour-library.jpg');

const SLIDE_MS = 5200;
const TICK_MS = 60;

const SLIDES = [
  {
    kicker: 'Prompt',
    title: "Tell the agent what\nyou're picturing",
    body: 'Describe the piece in plain language — carat, stone, metal, vibe. Grok creates the concept; Facetta turns it into a structured, physically validated spec.',
    image: promptShot,
  },
  {
    kicker: 'Refine',
    title: 'Adjust every detail,\nprecisely',
    body: "Fine-tune stone, cut, setting, and metal from a jeweler's own controlled vocabulary — never a free-text guess, always the trade language your factory expects.",
    image: adjustShot,
  },
  {
    kicker: 'Dimensions',
    title: 'Estimated millimeters,\nor your own',
    body: 'Let carat and cut derive the millimeters automatically, or switch to Pro mode and dial in exact length, width, and depth — the validator keeps every number physically possible.',
    image: dimsShot,
  },
  {
    kicker: 'Production',
    title: 'A factory sheet,\nevery time',
    body: 'One tap compiles an annotated technical sheet with every dimension lettered and traceable — ready to download and send straight to the workshop.',
    image: sheetShot,
  },
  {
    kicker: 'Presentation',
    title: 'Stunning renders,\non demand',
    body: 'See the piece the way your client will — photoreal, editorial, on demand — before a single stone is set.',
    image: renderShot,
  },
  {
    kicker: 'Library',
    title: 'Every piece,\norganized',
    body: 'Every save lives in your library — grouped by client, filtered by type — with every version on the record, forever.',
    image: libraryShot,
  },
];

function ProgressBar({ index, elapsed, onJump }: { index: number; elapsed: number; onJump: (i: number) => void }) {
  return (
    <View style={styles.progressRow}>
      {SLIDES.map((_, i) => {
        const pct = i < index ? 100 : i > index ? 0 : Math.min(100, (elapsed / SLIDE_MS) * 100);
        return (
          <Pressable key={i} style={styles.progressTrack} onPress={() => onJump(i)}>
            <View style={[styles.progressFill, { width: `${pct}%` }]} />
          </Pressable>
        );
      })}
    </View>
  );
}

/** Fades + slides content in on mount; re-keyed per slide for a clean transition. */
function SlideReveal({ children }: { children: React.ReactNode }) {
  const t = React.useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(t, {
      toValue: 1,
      duration: 380,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [t]);
  return (
    <Animated.View
      style={{
        flex: 1,
        opacity: t,
        transform: [{ translateY: t.interpolate({ inputRange: [0, 1], outputRange: [16, 0] }) }],
      }}>
      {children}
    </Animated.View>
  );
}

export function WorkflowShowcase({ onDone }: { onDone: () => void }) {
  const [index, setIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [paused, setPaused] = useState(false);
  const [finished, setFinished] = useState(false);
  const last = index === SLIDES.length - 1;

  useEffect(() => {
    setElapsed(0);
  }, [index]);

  useEffect(() => {
    if (paused || finished) return undefined;
    const id = setInterval(() => {
      setElapsed((e) => Math.min(SLIDE_MS, e + TICK_MS));
    }, TICK_MS);
    return () => clearInterval(id);
  }, [index, paused, finished]);

  useEffect(() => {
    if (elapsed < SLIDE_MS) return;
    if (last) {
      setFinished(true);
    } else {
      setIndex((i) => i + 1);
    }
  }, [elapsed, last]);

  const jump = (i: number) => {
    setFinished(false);
    setIndex(i);
  };
  const goNext = () => (last ? setFinished(true) : setIndex((i) => i + 1));
  const goPrev = () => {
    if (index === 0) return;
    setFinished(false);
    setIndex((i) => i - 1);
  };

  const { kicker, title, body, image } = SLIDES[index];

  return (
    <View style={styles.root}>
      <MotionBackground intensity={0.5} />

      <ProgressBar index={index} elapsed={elapsed} onJump={jump} />

      <View style={styles.topBar}>
        <Text style={styles.wordmark}>F A C E T T A</Text>
        <Pressable onPress={onDone} hitSlop={12}>
          <Text style={styles.skip}>Skip</Text>
        </Pressable>
      </View>

      <SlideReveal key={index}>
        <View style={styles.content}>
          <View style={styles.imageWrap}>
            <View style={[styles.imageCard, shadows.lifted]}>
              <Image source={image} style={styles.image} resizeMode="cover" />
              <Pressable
                style={styles.tapZoneLeft}
                onPress={goPrev}
                accessibilityLabel="Previous step"
              />
              <Pressable
                style={styles.tapZoneRight}
                onPress={goNext}
                accessibilityLabel="Next step"
              />
              <Pressable
                style={[styles.pauseButton, shadows.soft]}
                onPress={() => setPaused((p) => !p)}
                hitSlop={8}>
                <Text style={styles.pauseButtonText}>{paused ? '▶' : '❚❚'}</Text>
              </Pressable>
            </View>
          </View>
          <Text style={styles.kicker}>{kicker}</Text>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.body}>{body}</Text>
          {index === 0 && !finished && (
            <Text style={styles.hint}>tap right to skip ahead · tap left to go back</Text>
          )}
        </View>
      </SlideReveal>

      <View style={styles.footer}>
        {finished ? (
          <Pressable style={[styles.cta, shadows.soft]} onPress={onDone}>
            <Text style={styles.ctaText}>Continue</Text>
          </Pressable>
        ) : (
          <Text style={styles.stepCount}>
            {index + 1} / {SLIDES.length}
          </Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  progressRow: {
    flexDirection: 'row',
    gap: 5,
    paddingHorizontal: 20,
    paddingTop: 14,
  },
  progressTrack: {
    flex: 1,
    height: 3,
    borderRadius: 2,
    backgroundColor: theme.line,
    overflow: 'hidden',
  },
  progressFill: { height: '100%', backgroundColor: theme.gold, borderRadius: 2 },
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingTop: 12,
  },
  wordmark: { fontFamily: theme.serif, fontSize: 14, letterSpacing: 4, color: theme.ink },
  skip: { fontSize: 14, color: theme.faint },
  content: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 26, paddingTop: 6 },
  imageWrap: { width: '100%', maxWidth: 340, marginBottom: 22 },
  imageCard: {
    width: '100%',
    aspectRatio: 430 / 550,
    borderRadius: radius.xl,
    backgroundColor: theme.card,
    borderWidth: 1,
    borderColor: theme.line,
    overflow: 'hidden',
  },
  image: { width: '100%', height: '100%' },
  tapZoneLeft: { position: 'absolute', left: 0, top: 0, bottom: 0, width: '32%' },
  tapZoneRight: { position: 'absolute', right: 0, top: 0, bottom: 0, width: '68%' },
  pauseButton: {
    position: 'absolute',
    right: 10,
    bottom: 10,
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: 'rgba(253, 253, 250, 0.92)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  pauseButtonText: { fontSize: 12, color: theme.ink },
  kicker: {
    fontSize: 12,
    letterSpacing: 3,
    textTransform: 'uppercase',
    color: theme.gold,
    marginBottom: 8,
  },
  title: {
    fontFamily: theme.serif,
    fontSize: 22,
    lineHeight: 28,
    color: theme.ink,
    textAlign: 'center',
    marginBottom: 10,
  },
  body: {
    fontSize: 14,
    lineHeight: 21,
    color: theme.faint,
    textAlign: 'center',
    maxWidth: 340,
  },
  hint: {
    fontSize: 11,
    color: theme.faint,
    fontStyle: 'italic',
    marginTop: 14,
    opacity: 0.8,
  },
  footer: { alignItems: 'center', paddingBottom: 30, paddingHorizontal: 32, minHeight: 66, justifyContent: 'center' },
  stepCount: { fontSize: 12, color: theme.faint, letterSpacing: 1 },
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
});
