import type { PreviewCheck } from './contracts';

export type InternalReviewVerdict = 'pass' | 'warn' | 'reject' | 'fail';

type ReviewCheckIdentity = Partial<Pick<PreviewCheck, 'id' | 'label'>>;

function isFactoryAuthorityCheck(check: ReviewCheckIdentity): boolean {
  return check.id === 'factory_authority';
}

export function designerReviewState(
  verdict: InternalReviewVerdict,
  check: ReviewCheckIdentity = {},
): string {
  if (isFactoryAuthorityCheck(check)) return 'Review-only render';
  if (verdict === 'pass') return 'Design preserved';
  if (verdict === 'warn') return 'Review recommended';
  return 'Could not preserve design';
}

export function designerCheckLabel(check: Pick<PreviewCheck, 'id' | 'label'>): string {
  if (isFactoryAuthorityCheck(check)) return 'Not production data';
  const value = `${check.id} ${check.label}`.toLowerCase();
  if (/(drift|geometry|identity|silhouette|proportion|topology|count|component|placement|shape|form)/.test(value)) {
    return 'Design preservation';
  }
  if (/(material|metal|color|finish|surface)/.test(value)) {
    return 'Material appearance';
  }
  if (/(crop|frame|view|angle|background|shadow|lighting|text|watermark|composition)/.test(value)) {
    return 'Image presentation';
  }
  if (/(setting|prong|mount|seat|gallery|clearance|attachment|intersection|hardware|chain|clasp)/.test(value)) {
    return 'Construction consistency';
  }
  // Review labels originate below the Studio seam. Unknown labels must not
  // surface provider names, evaluator jargon, internal codes, or prompt text
  // in the designer interface. The exact evidence remains durable server-side.
  return 'Visual consistency';
}

export function designerCheckDetail(
  check: Pick<PreviewCheck, 'verdict'> & ReviewCheckIdentity,
): string {
  if (isFactoryAuthorityCheck(check)) {
    return 'This visual does not establish dimensions, materials, or factory facts.';
  }
  if (check.verdict === 'pass') {
    return 'No meaningful unintended change was detected.';
  }
  if (check.verdict === 'warn') {
    return 'Compare this area carefully with the source before applying.';
  }
  return 'This area changed too much from the selected source.';
}
