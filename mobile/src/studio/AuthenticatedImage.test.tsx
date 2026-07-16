/// <reference types="jest" />

import React from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react-native';
import { Platform } from 'react-native';
import { AuthenticatedImage, AuthenticatedImageProvider } from '../AuthenticatedImage';

const fetchMock = jest.fn<ReturnType<typeof fetch>, Parameters<typeof fetch>>();
const createObjectURLMock = jest.fn<string, [Blob]>();
const revokeObjectURLMock = jest.fn<void, [string]>();

const originalPlatformOS = Platform.OS;
const originalFetchDescriptor = Object.getOwnPropertyDescriptor(global, 'fetch');
const originalCreateObjectURLDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
const originalRevokeObjectURLDescriptor = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');

function setPlatformOS(os: typeof Platform.OS): void {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: os });
}

function restoreProperty(
  target: object,
  property: string,
  descriptor: PropertyDescriptor | undefined,
): void {
  if (descriptor === undefined) {
    delete (target as Record<string, unknown>)[property];
    return;
  }
  Object.defineProperty(target, property, descriptor);
}

function responseWith({
  ok = true,
  contentType = 'image/png',
  size = 8,
}: {
  ok?: boolean;
  contentType?: string | null;
  size?: number;
} = {}): Response {
  return {
    ok,
    headers: {
      get: jest.fn((name: string) => (
        name.toLowerCase() === 'content-type' ? contentType : null
      )),
    },
    blob: jest.fn().mockResolvedValue({ size, type: contentType ?? '' } as Blob),
  } as unknown as Response;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function protectedImage({
  source = '/assets/asset_1/image',
  label = 'Protected design',
  onError,
  onLoad,
}: {
  source?: string;
  label?: string;
  onError?: jest.Mock;
  onLoad?: jest.Mock;
} = {}) {
  return (
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test/api"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <AuthenticatedImage
        accessibilityLabel={label}
        onError={onError}
        onLoad={onLoad}
        source={{ uri: source }}
      />
    </AuthenticatedImageProvider>
  );
}

beforeAll(() => {
  Object.defineProperty(global, 'fetch', { configurable: true, writable: true, value: fetchMock });
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: createObjectURLMock,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: revokeObjectURLMock,
  });
});

beforeEach(() => {
  setPlatformOS('ios');
  fetchMock.mockReset();
  createObjectURLMock.mockReset();
  revokeObjectURLMock.mockReset();
});

afterAll(() => {
  setPlatformOS(originalPlatformOS);
  restoreProperty(global, 'fetch', originalFetchDescriptor);
  restoreProperty(URL, 'createObjectURL', originalCreateObjectURLDescriptor);
  restoreProperty(URL, 'revokeObjectURL', originalRevokeObjectURLDescriptor);
});

test('same-origin protected images retain native runtime bearer headers', async () => {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test/api"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <AuthenticatedImage
        accessibilityLabel="Same-origin design"
        source={{
          uri: 'https://facetta.test/assets/asset_1/image',
          headers: { Authorization: 'Bearer attacker-value' },
        }}
      />
    </AuthenticatedImageProvider>,
  );
  expect(screen.getByLabelText('Same-origin design').props.source.headers).toEqual({
    Authorization: 'Bearer runtime-token',
  });
  expect(fetchMock).not.toHaveBeenCalled();
});

test('relative protected image paths retain native trusted-origin resolution and authorization', async () => {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test/api"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <AuthenticatedImage
        accessibilityLabel="Relative design"
        source={{ uri: '/assets/asset_1/image' }}
      />
    </AuthenticatedImageProvider>,
  );
  expect(screen.getByLabelText('Relative design').props.source).toMatchObject({
    uri: 'https://facetta.test/assets/asset_1/image',
    headers: { Authorization: 'Bearer runtime-token' },
  });
});

test('bundled Expo web assets stay on the page origin without private API fetching', async () => {
  setPlatformOS('web');
  const bundledSource = {
    uri: '/assets/?unstable_path=.%2Fassets/studio-ring.png',
    width: 960,
    height: 1200,
  };

  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test/api"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <AuthenticatedImage
        accessibilityLabel="Bundled inspiration"
        source={bundledSource}
      />
    </AuthenticatedImageProvider>,
  );

  expect(screen.getByLabelText('Bundled inspiration').props.source).toEqual(bundledSource);
  expect(fetchMock).not.toHaveBeenCalled();
});

test('off-origin images fail closed without leaking Facetta authorization', async () => {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <AuthenticatedImage
        accessibilityLabel="Foreign image"
        source={{ uri: 'https://evil.example/collect.png' }}
      />
    </AuthenticatedImageProvider>,
  );
  const locked = screen.getByLabelText('Foreign image unavailable: untrusted image origin');
  expect(locked.props.source).toBeUndefined();
  expect(screen.getByText('Image origin could not be verified')).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});

test('missing runtime token shows a fail-closed sign-in placeholder', async () => {
  await render(
    <AuthenticatedImageProvider allowedOrigin="https://facetta.test" headers={undefined}>
      <AuthenticatedImage
        accessibilityLabel="Private design"
        source={{ uri: 'https://facetta.test/assets/asset_1/image' }}
      />
    </AuthenticatedImageProvider>,
  );
  expect(screen.getByLabelText('Private design unavailable: sign in required')).toBeTruthy();
  expect(screen.getByText('Sign in to view this image')).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});

describe('web protected image loading', () => {
  beforeEach(() => {
    setPlatformOS('web');
  });

  test('fetches only the resolved trusted URL with auth and renders a header-free object URL', async () => {
    const onLoad = jest.fn();
    const imageBlob = { size: 8, type: 'image/png' } as Blob;
    const response = responseWith();
    const pendingResponse = deferred<Response>();
    (response.blob as jest.Mock).mockResolvedValue(imageBlob);
    fetchMock.mockReturnValue(pendingResponse.promise);
    createObjectURLMock.mockReturnValue('blob:facetta-image');

    await render(protectedImage({ label: 'Web design', onLoad }));

    expect(screen.getByLabelText('Web design loading')).toBeTruthy();
    await act(async () => {
      pendingResponse.resolve(response);
      await pendingResponse.promise;
    });
    await waitFor(() => expect(screen.getByLabelText('Web design')).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      'https://facetta.test/assets/asset_1/image',
      {
        headers: { Authorization: 'Bearer runtime-token' },
        signal: expect.anything(),
      },
    );
    expect(createObjectURLMock).toHaveBeenCalledWith(imageBlob);
    expect(screen.getByLabelText('Web design').props.source).toEqual({
      uri: 'blob:facetta-image',
    });

    fireEvent(screen.getByLabelText('Web design'), 'load');
    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  test('uses a generic retryable error without leaking a URL, token, or fetch failure', async () => {
    const onError = jest.fn();
    fetchMock.mockRejectedValue(new Error(
      'Bearer runtime-token failed at https://facetta.test/assets/asset_1/image',
    ));

    const view = await render(protectedImage({ label: 'Safe failure', onError }));

    await waitFor(() => expect(screen.getByText('Image could not be loaded')).toBeTruthy());
    expect(screen.getByLabelText('Safe failure retry')).toBeTruthy();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].nativeEvent.error).toBe('Image could not be loaded.');
    const rendered = JSON.stringify(view.toJSON());
    expect(rendered).not.toContain('runtime-token');
    expect(rendered).not.toContain('facetta.test');
  });

  test('retries a failed request and becomes reviewable after the later image loads', async () => {
    const onLoad = jest.fn();
    fetchMock
      .mockResolvedValueOnce(responseWith({ ok: false }))
      .mockResolvedValueOnce(responseWith());
    createObjectURLMock.mockReturnValue('blob:retried-image');

    await render(protectedImage({ label: 'Retryable design', onLoad }));

    await waitFor(() => expect(screen.getByLabelText('Retryable design retry')).toBeTruthy());
    fireEvent.press(screen.getByLabelText('Retryable design retry'));
    await waitFor(() => expect(screen.getByLabelText('Retryable design')).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fireEvent(screen.getByLabelText('Retryable design'), 'load');
    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  test('bounds retries to three failed attempts', async () => {
    fetchMock.mockResolvedValue(responseWith({ ok: false }));
    await render(protectedImage({ label: 'Bounded design' }));

    await waitFor(() => expect(screen.getByLabelText('Bounded design retry')).toBeTruthy());
    fireEvent.press(screen.getByLabelText('Bounded design retry'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    fireEvent.press(screen.getByLabelText('Bounded design retry'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.queryByLabelText('Bounded design retry')).toBeNull());
  });

  test('revokes the prior object URL when the protected source is replaced', async () => {
    fetchMock.mockResolvedValue(responseWith());
    createObjectURLMock
      .mockReturnValueOnce('blob:first-image')
      .mockReturnValueOnce('blob:second-image');
    const view = await render(protectedImage({ source: '/assets/first/image', label: 'Replaceable design' }));

    await waitFor(() => expect(screen.getByLabelText('Replaceable design').props.source.uri)
      .toBe('blob:first-image'));
    await view.rerender(protectedImage({ source: '/assets/second/image', label: 'Replaceable design' }));

    await waitFor(() => expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:first-image'));
    await waitFor(() => expect(screen.getByLabelText('Replaceable design').props.source.uri)
      .toBe('blob:second-image'));
  });

  test('revokes the current object URL on unmount', async () => {
    fetchMock.mockResolvedValue(responseWith());
    createObjectURLMock.mockReturnValue('blob:unmounted-image');
    const view = await render(protectedImage({ label: 'Unmounted design' }));

    await waitFor(() => expect(screen.getByLabelText('Unmounted design')).toBeTruthy());
    await view.unmount();

    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:unmounted-image');
  });

  test('suppresses a stale request completion after a source replacement', async () => {
    const firstResponse = deferred<Response>();
    fetchMock
      .mockReturnValueOnce(firstResponse.promise)
      .mockResolvedValueOnce(responseWith());
    createObjectURLMock.mockReturnValue('blob:current-image');
    const view = await render(protectedImage({ source: '/assets/slow/image', label: 'Current design' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await view.rerender(protectedImage({ source: '/assets/current/image', label: 'Current design' }));
    await waitFor(() => expect(screen.getByLabelText('Current design').props.source.uri)
      .toBe('blob:current-image'));

    await act(async () => {
      firstResponse.resolve(responseWith());
      await firstResponse.promise;
    });
    expect(createObjectURLMock).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Current design').props.source.uri).toBe('blob:current-image');
  });

  test('rejects a successful non-image response before creating an object URL', async () => {
    const onError = jest.fn();
    fetchMock.mockResolvedValue(responseWith({ contentType: 'application/json' }));

    await render(protectedImage({ label: 'Non-image design', onError }));

    await waitFor(() => expect(screen.getByText('Image could not be loaded')).toBeTruthy());
    expect(createObjectURLMock).not.toHaveBeenCalled();
    expect(onError.mock.calls[0][0].nativeEvent.error).toBe('Image could not be loaded.');
  });

  test('rejects an empty image blob before creating an object URL', async () => {
    const onError = jest.fn();
    fetchMock.mockResolvedValue(responseWith({ size: 0 }));

    await render(protectedImage({ label: 'Empty design', onError }));

    await waitFor(() => expect(screen.getByText('Image could not be loaded')).toBeTruthy());
    expect(createObjectURLMock).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledTimes(1);
  });
});
