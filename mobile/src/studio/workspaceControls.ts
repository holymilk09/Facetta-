import type { ReferenceRole } from './contracts';

export const STUDIO_CREATE_REFERENCE_CONTROLS = [
  {
    fieldId: 'master',
    role: 'master_geometry',
    label: 'Optional source image',
    help: 'Upload your own drawing, photograph, or existing render when you want Facetta to visualize it.',
  },
] as const satisfies readonly {
  fieldId: string; role: ReferenceRole; label: string; help: string;
}[];

export type CreateReferenceRole = typeof STUDIO_CREATE_REFERENCE_CONTROLS[number]['role'];

export const STUDIO_PRESENT_CONTROLS = {
  destination: { fieldId: 'destination', label: 'Destination' },
  direction: { fieldId: 'direction', label: 'Optional art direction' },
} as const;
