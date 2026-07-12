const mockGetDocumentAsync = jest.fn();
const mockReadBase64 = jest.fn();

jest.mock('expo-document-picker', () => ({
  getDocumentAsync: (...args: unknown[]) => mockGetDocumentAsync(...args),
}));

jest.mock('expo-file-system', () => ({
  File: class MockFile {
    readonly uri: string;

    constructor(uri: string) {
      this.uri = uri;
    }

    base64(): Promise<string> {
      return mockReadBase64(this.uri);
    }
  },
}));

import { pickExpoStudioCreateReference } from './expoReferencePicker';

describe('Expo Studio reference picker adapter', () => {
  beforeEach(() => {
    mockGetDocumentAsync.mockReset();
    mockReadBase64.mockReset();
  });

  test('opens a single-image picker and reads native cached bytes', async () => {
    mockGetDocumentAsync.mockResolvedValue({
      canceled: false,
      assets: [{
        name: 'ring.png',
        uri: 'file:///cache/ring.png',
        mimeType: 'image/png',
      }],
    });
    mockReadBase64.mockResolvedValue('cmluZw==');

    const result = await pickExpoStudioCreateReference('master_geometry');

    expect(mockGetDocumentAsync).toHaveBeenCalledWith({
      type: ['image/png', 'image/jpeg', 'image/webp'],
      copyToCacheDirectory: true,
      multiple: false,
      base64: true,
    });
    expect(mockReadBase64).toHaveBeenCalledWith('file:///cache/ring.png');
    expect(result).toEqual(expect.objectContaining({
      role: 'master_geometry',
      label: 'ring.png',
      imageBase64: 'cmluZw==',
      mediaType: 'image/png',
    }));
  });

  test('treats cancel as a normal no-selection outcome', async () => {
    mockGetDocumentAsync.mockResolvedValue({ canceled: true, assets: null });

    await expect(pickExpoStudioCreateReference('brand_direction')).resolves.toBeNull();
    expect(mockReadBase64).not.toHaveBeenCalled();
  });
});

