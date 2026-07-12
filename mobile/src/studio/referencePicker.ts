import type {
  CreateReferenceRole,
  StudioCreateReference,
} from './StudioCreateWorkspace';

export const STUDIO_REFERENCE_MEDIA_TYPES = [
  'image/png',
  'image/jpeg',
  'image/webp',
] as const;

export type StudioReferenceMediaType = typeof STUDIO_REFERENCE_MEDIA_TYPES[number];

export interface StudioReferencePickerAsset {
  name: string;
  uri: string;
  mimeType?: string;
  base64?: string;
}

export interface StudioReferencePickerAdapter {
  pick: () => Promise<StudioReferencePickerAsset | null>;
  readBase64: (uri: string) => Promise<string>;
  makeId?: (role: CreateReferenceRole, asset: StudioReferencePickerAsset) => string;
}

function mediaTypeFromAsset(asset: StudioReferencePickerAsset): StudioReferenceMediaType | null {
  const declared = asset.mimeType?.trim().toLowerCase();
  if (declared === 'image/png') return 'image/png';
  if (declared === 'image/jpeg' || declared === 'image/jpg') return 'image/jpeg';
  if (declared === 'image/webp') return 'image/webp';

  const cleanName = asset.name.toLowerCase().split(/[?#]/, 1)[0];
  if (cleanName.endsWith('.png')) return 'image/png';
  if (cleanName.endsWith('.jpg') || cleanName.endsWith('.jpeg')) return 'image/jpeg';
  if (cleanName.endsWith('.webp')) return 'image/webp';
  return null;
}

function rawBase64(value: string): string {
  const trimmed = value.trim();
  const marker = ';base64,';
  const markerIndex = trimmed.indexOf(marker);
  return markerIndex === -1 ? trimmed : trimmed.slice(markerIndex + marker.length);
}

/**
 * Pick one role-labeled Studio reference without making it authoritative.
 * The adapter keeps the validation deterministic and lets Expo provide the
 * platform-specific picker and file reader at the application boundary.
 */
export async function pickStudioCreateReference(
  role: CreateReferenceRole,
  adapter: StudioReferencePickerAdapter,
): Promise<StudioCreateReference | null> {
  const asset = await adapter.pick();
  if (asset === null) return null;

  const mediaType = mediaTypeFromAsset(asset);
  if (mediaType === null) {
    throw new Error('Choose a PNG, JPEG, or WebP image. Other file types are not supported.');
  }

  const imageBase64 = rawBase64(asset.base64 ?? await adapter.readBase64(asset.uri));
  if (!imageBase64) {
    throw new Error('The selected image could not be read. Choose another file and try again.');
  }

  return {
    id: adapter.makeId?.(role, asset)
      ?? `${role}:${Date.now()}:${Math.random().toString(36).slice(2)}`,
    role,
    label: asset.name,
    imageBase64,
    mediaType,
  };
}

