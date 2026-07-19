import type { ReferenceRole } from './contracts';

export const STUDIO_CREATE_REFERENCE_CONTROLS = [
  { fieldId: 'master', role: 'master_geometry', label: 'Master geometry', help: 'The source design whose visible form must be preserved.' },
  { fieldId: 'style', role: 'material_style', label: 'Material & finish', help: 'Choose metal color, surface, finish, or palette. These choices never define the jewelry’s shape.' },
  { fieldId: 'construction', role: 'construction_detail', label: 'Specific design detail', help: 'Optional visual guidance for a detail such as prongs, gallery, clasp, hinge, or link profile—not a confirmed production fact.' },
  { fieldId: 'brand', role: 'brand_direction', label: 'Brand mood', help: 'Choose the feeling and visual language, such as quiet luxury or bold editorial. This never copies branding or jewelry geometry.' },
] as const satisfies readonly {
  fieldId: string; role: ReferenceRole; label: string; help: string;
}[];

export type CreateReferenceRole = typeof STUDIO_CREATE_REFERENCE_CONTROLS[number]['role'];

export const STUDIO_PRESENT_CONTROLS = {
  destination: { fieldId: 'destination', label: 'Destination' },
  direction: { fieldId: 'direction', label: 'Optional art direction' },
} as const;
