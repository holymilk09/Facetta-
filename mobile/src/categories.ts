// Per-category builder metadata: which templates exist, which cuts each
// accepts, and sensible defaults. The controlled values themselves (species,
// colors, clarity, chains, clasps) always come from the vocabulary API.

export type Category = 'ring' | 'bracelet' | 'pendant' | 'loose';

export const CATEGORIES: { id: Category; label: string }[] = [
  { id: 'ring', label: 'Ring' },
  { id: 'bracelet', label: 'Bracelet / Cuff' },
  { id: 'pendant', label: 'Pendant / Necklace' },
  { id: 'loose', label: 'Loose stone' },
];

export const RING_TEMPLATES = [
  { id: 'solitaire_prong', label: 'Solitaire' },
  { id: 'halo_prong', label: 'Halo' },
] as const;

export const BRACELET_KINDS = [
  { id: 'love_bangle', label: 'Bangle' },
  { id: 'cuff', label: 'Open cuff' },
  { id: 'link_bracelet', label: 'Link bracelet' },
] as const;

// cuts each sheet template can draw; the chip row filters to these
export const CATEGORY_CUTS: Record<Category, string[] | null> = {
  ring: ['round_brilliant', 'oval_brilliant'],
  bracelet: ['princess', 'asscher'],
  pendant: ['emerald_cut', 'asscher', 'radiant'],
  loose: null, // any cut — the gem sheet draws brilliant or step outlines
};

export const DEFAULTS = {
  ring: { species: 'sapphire', cut: 'oval_brilliant', carat: '2.0' },
  bracelet: { species: 'diamond', cut: 'princess', carat: '0.14' },
  pendant: { species: 'emerald', cut: 'emerald_cut', carat: '1.9' },
  loose: { species: 'diamond', cut: 'round_brilliant', carat: '2.0' },
} as const;
