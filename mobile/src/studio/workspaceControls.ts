import type { ReferenceRole } from './contracts';

export const STUDIO_CREATE_REFERENCE_CONTROLS = [
  { fieldId: 'master', role: 'master_geometry', label: 'Master geometry', help: 'The source design whose visible form must be preserved.' },
  { fieldId: 'style', role: 'material_style', label: 'Material & style', help: 'Surface, color, and finish only—not jewelry geometry.' },
  { fieldId: 'construction', role: 'construction_detail', label: 'Construction detail', help: 'Visual guidance for one detail, not a confirmed production fact.' },
  { fieldId: 'brand', role: 'brand_direction', label: 'Brand direction', help: 'Mood and visual language only—not product geometry or branding to copy.' },
] as const satisfies readonly {
  fieldId: string; role: ReferenceRole; label: string; help: string;
}[];

export type CreateReferenceRole = typeof STUDIO_CREATE_REFERENCE_CONTROLS[number]['role'];

export const STUDIO_PRESENT_CONTROLS = {
  destination: { fieldId: 'destination', label: 'Destination' },
  direction: { fieldId: 'direction', label: 'Optional art direction' },
} as const;
