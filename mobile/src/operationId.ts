let operationSequence = 0;

/**
 * Create a compact client operation id for durable, server-side idempotency.
 * It is a uniqueness key, not an authentication secret.
 */
export function createClientOperationId(prefix: string): string {
  operationSequence = (operationSequence + 1) % 0x100000000;
  const randomWord = (): string => Math.floor(
    Math.random() * 0x100000000,
  ).toString(16).padStart(8, '0');
  const sequence = operationSequence.toString(16).padStart(8, '0');
  return `${prefix}:${Date.now().toString(36)}:${sequence}:${randomWord()}`;
}
