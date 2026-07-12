import * as DocumentPicker from 'expo-document-picker';
import { File } from 'expo-file-system';

import type { CreateReferenceRole, StudioCreateReference } from './StudioCreateWorkspace';
import {
  pickStudioCreateReference,
  STUDIO_REFERENCE_MEDIA_TYPES,
} from './referencePicker';

/** Open the native/web document picker and return one validated Studio image. */
export function pickExpoStudioCreateReference(
  role: CreateReferenceRole,
): Promise<StudioCreateReference | null> {
  return pickStudioCreateReference(role, {
    pick: async () => {
      const result = await DocumentPicker.getDocumentAsync({
        type: [...STUDIO_REFERENCE_MEDIA_TYPES],
        copyToCacheDirectory: true,
        multiple: false,
        // On web this avoids a second FileReader pass. Native falls back to
        // expo-file-system below because DocumentPicker does not return base64.
        base64: true,
      });
      if (result.canceled) return null;
      const asset = result.assets[0];
      if (asset === undefined) {
        throw new Error('No image was returned by the file picker. Please try again.');
      }
      return {
        name: asset.name,
        uri: asset.uri,
        mimeType: asset.mimeType,
        base64: asset.base64,
      };
    },
    readBase64: (uri) => new File(uri).base64(),
  });
}

