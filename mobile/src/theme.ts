// Pencil-and-paper palette to match the technical sheets.
export const theme = {
  paper: '#fdfdfa',
  card: '#ffffff',
  ink: '#3f3f3f',
  faint: '#8a8a8a',
  line: '#d8d5cc',
  accent: '#8a6d3b',
  gold: '#b08d4f',
  goldSoft: '#efe6d2',
  blush: '#f6efe7',
  danger: '#a03030',
  ok: '#3b6e46',
  serif: 'Georgia',
};

// Corner radii — everything rounded, nothing sharp.
export const radius = {
  sm: 10,
  md: 16,
  lg: 22,
  xl: 28,
  pill: 999,
};

// Soft layered shadows (elevation covers Android, shadow* covers iOS/web).
export const shadows = {
  soft: {
    shadowColor: '#5b4a2f',
    shadowOpacity: 0.08,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
  },
  lifted: {
    shadowColor: '#5b4a2f',
    shadowOpacity: 0.14,
    shadowRadius: 22,
    shadowOffset: { width: 0, height: 10 },
    elevation: 8,
  },
  floating: {
    shadowColor: '#3f3f3f',
    shadowOpacity: 0.18,
    shadowRadius: 30,
    shadowOffset: { width: 0, height: 16 },
    elevation: 12,
  },
} as const;

// Line-art stroke colors for the motion background sketches.
export const sketchInk = (alpha: number) => `rgba(63, 63, 63, ${alpha})`;
export const sketchGold = (alpha: number) => `rgba(176, 141, 79, ${alpha})`;
