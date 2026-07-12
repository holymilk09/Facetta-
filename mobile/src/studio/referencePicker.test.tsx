import {
  pickStudioCreateReference,
  type StudioReferencePickerAdapter,
} from './referencePicker';

function adapter(
  asset: Awaited<ReturnType<StudioReferencePickerAdapter['pick']>>,
  readBase64: StudioReferencePickerAdapter['readBase64'] = async () => 'bmF0aXZl',
): StudioReferencePickerAdapter {
  return {
    pick: async () => asset,
    readBase64,
    makeId: (role) => `ref:${role}`,
  };
}

describe('Studio reference picker', () => {
  test('returns null when the designer cancels', async () => {
    await expect(pickStudioCreateReference('master_geometry', adapter(null))).resolves.toBeNull();
  });

  test('keeps the selected role and accepts web-provided base64', async () => {
    const readBase64 = jest.fn(async () => 'unused');
    const result = await pickStudioCreateReference('material_style', adapter({
      name: 'finish.WEBP',
      uri: 'blob:finish',
      mimeType: 'image/webp',
      base64: 'data:image/webp;base64,d2VicA==',
    }, readBase64));

    expect(result).toEqual({
      id: 'ref:material_style',
      role: 'material_style',
      label: 'finish.WEBP',
      imageBase64: 'd2VicA==',
      mediaType: 'image/webp',
    });
    expect(readBase64).not.toHaveBeenCalled();
  });

  test('reads native files and infers JPEG from a trustworthy extension', async () => {
    const readBase64 = jest.fn(async () => 'anBlZw==');
    const result = await pickStudioCreateReference('construction_detail', adapter({
      name: 'setting.JPEG',
      uri: 'file:///cache/setting.JPEG',
      mimeType: 'application/octet-stream',
    }, readBase64));

    expect(result?.mediaType).toBe('image/jpeg');
    expect(result?.imageBase64).toBe('anBlZw==');
    expect(readBase64).toHaveBeenCalledWith('file:///cache/setting.JPEG');
  });

  test('rejects unsupported and unreadable files with designer-facing messages', async () => {
    await expect(pickStudioCreateReference('brand_direction', adapter({
      name: 'brand.svg', uri: 'file:///brand.svg', mimeType: 'image/svg+xml',
    }))).rejects.toThrow('Choose a PNG, JPEG, or WebP image');

    await expect(pickStudioCreateReference('master_geometry', adapter({
      name: 'ring.png', uri: 'file:///ring.png', mimeType: 'image/png',
    }, async () => '   '))).rejects.toThrow('could not be read');
  });
});

