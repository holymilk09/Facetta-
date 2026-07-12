import type { PreviewCheck } from './contracts';

export type InternalReviewVerdict = 'pass' | 'warn' | 'reject' | 'fail';

export function designerReviewState(verdict: InternalReviewVerdict): string {
  if (verdict === 'pass') return 'Design preserved';
  if (verdict === 'warn') return 'Review recommended';
  return 'Could not preserve design';
}

export function designerCheckLabel(check: Pick<PreviewCheck, 'id' | 'label'>): string {
  const value = `${check.id} ${check.label}`.toLowerCase();
  if (/(drift|geometry|identity|silhouette|proportion)/.test(value)) {
    return 'Design preservation';
  }
  if (/(material|metal|color|finish|surface)/.test(value)) {
    return 'Material appearance';
  }
  return check.label;
}

export function designerCheckDetail(
  check: Pick<PreviewCheck, 'verdict'>,
): string {
  if (check.verdict === 'pass') {
    return 'No meaningful unintended change was detected.';
  }
  if (check.verdict === 'warn') {
    return 'Compare this area carefully with the source before applying.';
  }
  return 'This area changed too much from the selected source.';
}
