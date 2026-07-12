import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, ChipRow, Field, Notice } from '../components';
import { theme } from '../theme';
import type {
  SourceComponentResolution,
  SourceCoverageComponent,
  SourceCoverageResolutionResult,
} from './types';

export type SourceCoverageCorrectionMode = 'mapped' | 'unresolved';

export interface SourceCoverageCorrectionDraft {
  mode: SourceCoverageCorrectionMode;
  selected_paths: string[];
  unresolved_note: string;
}

export type SourceCoverageCorrectionDrafts = Record<
string,
SourceCoverageCorrectionDraft
>;

export function sourceCoverageDrafts(
  components: SourceCoverageComponent[],
): SourceCoverageCorrectionDrafts {
  return Object.fromEntries(components.map((component) => [
    component.component_id,
    {
      mode: component.canonical_spec_paths.length > 0 ? 'mapped' : 'unresolved',
      selected_paths: [...component.canonical_spec_paths],
      unresolved_note: component.unresolved_reason ?? '',
    },
  ]));
}

const samePathSet = (left: string[], right: string[]): boolean =>
  left.length === right.length
  && left.every((path) => right.includes(path));

export function changedSourceCoverageResolutions(
  coverage: SourceCoverageResolutionResult,
  drafts: SourceCoverageCorrectionDrafts,
): SourceComponentResolution[] {
  const validPaths = new Set(coverage.valid_spec_paths);
  const resolutions: SourceComponentResolution[] = [];
  for (const component of coverage.components) {
    const draft = drafts[component.component_id];
    if (draft === undefined) continue;
    if (draft.mode === 'mapped') {
      const paths = [...new Set(draft.selected_paths)]
        .filter((path) => validPaths.has(path));
      if (paths.length === 0 || samePathSet(paths, component.canonical_spec_paths)
        && component.unresolved_reason === null) continue;
      resolutions.push({
        component_id: component.component_id,
        canonical_spec_paths: paths,
        unresolved_reason: null,
      });
      continue;
    }
    const note = draft.unresolved_note.trim();
    if (!note || component.canonical_spec_paths.length === 0
      && component.unresolved_reason === note) continue;
    resolutions.push({
      component_id: component.component_id,
      canonical_spec_paths: [],
      unresolved_reason: note,
    });
  }
  return resolutions;
}

export function sourceCoverageDraftsValid(
  coverage: SourceCoverageResolutionResult,
  drafts: SourceCoverageCorrectionDrafts,
): boolean {
  const validPaths = new Set(coverage.valid_spec_paths);
  return coverage.components.every((component) => {
    const draft = drafts[component.component_id];
    if (draft === undefined) return false;
    if (draft.mode === 'unresolved') return draft.unresolved_note.trim().length > 0;
    return draft.selected_paths.length > 0
      && draft.selected_paths.every((path) => validPaths.has(path));
  });
}

export function sourceCoverageAllowsCreation(
  coverage: SourceCoverageResolutionResult | null,
  specChangedAfterAudit: boolean,
): boolean {
  return coverage !== null
    && !specChangedAfterAudit
    && coverage.factory_ready
    && coverage.blockers.length === 0
    && coverage.audit.status === 'pass';
}

const viewLabel = (value: string): string => value.replace(/_/g, ' ');

export interface SourceCoverageCorrectionPanelProps {
  coverage: SourceCoverageResolutionResult;
  drafts: SourceCoverageCorrectionDrafts;
  busy: 'apply' | 'audit' | null;
  specChangedAfterAudit: boolean;
  onDraftChange: (
    componentId: string,
    draft: SourceCoverageCorrectionDraft,
  ) => void;
  onApply: () => void;
  onAudit: () => void;
}

export function SourceCoverageCorrectionPanel({
  coverage,
  drafts,
  busy,
  specChangedAfterAudit,
  onDraftChange,
  onApply,
  onAudit,
}: SourceCoverageCorrectionPanelProps) {
  const resolutions = changedSourceCoverageResolutions(coverage, drafts);
  const draftsValid = sourceCoverageDraftsValid(coverage, drafts);
  const auditPassed = sourceCoverageAllowsCreation(coverage, specChangedAfterAudit);

  return (
    <View style={styles.wrap}>
      <Text style={styles.heading}>Source component accounting</Text>
      <Notice
        kind="info"
        text="These observations account for what is visible in the uploaded reference. They do not prove dimensions, hidden construction, CAD geometry, or factory truth. Confirm measurements separately."
      />
      {specChangedAfterAudit && (
        <Notice
          kind="info"
          text="The specification JSON changed after the last audit. Re-run the independent source audit before creating the project."
        />
      )}
      {coverage.components.map((component) => {
        const draft = drafts[component.component_id] ?? {
          mode: 'unresolved' as const,
          selected_paths: [],
          unresolved_note: '',
        };
        const componentBlockers = coverage.blockers.filter(
          (blocker) => blocker.component_id === component.component_id,
        );
        return (
          <View key={component.component_id} style={styles.componentCard}>
            <Text style={styles.componentId}>{component.component_id}</Text>
            <Text style={styles.description}>{component.source_description}</Text>
            <Text style={styles.meta}>
              Source view: {viewLabel(component.source_view)} · visual-read confidence {Math.round(component.source_confidence * 100)}%
            </Text>
            <Text style={styles.currentMapping}>
              {component.canonical_spec_paths.length > 0
                ? `Current mapping: ${component.canonical_spec_paths.join(', ')}`
                : `Currently unresolved: ${component.unresolved_reason ?? 'designer note required'}`}
            </Text>
            {component.independent_audit === null ? (
              <Text style={styles.meta}>Independent audit: not yet retained</Text>
            ) : (
              <Text style={component.independent_audit.verdict === 'pass'
                ? styles.auditPass : styles.auditReview}>
                Independent audit {component.independent_audit.verdict}: {component.independent_audit.observed_description}
              </Text>
            )}
            <ChipRow
              label="Designer resolution"
              options={['mapped', 'unresolved'] as const}
              value={draft.mode}
              onSelect={(mode) => onDraftChange(component.component_id, {
                ...draft,
                mode,
              })}
              render={(mode) => mode === 'mapped'
                ? 'Map to existing spec paths'
                : 'Keep explicitly unresolved'}
              disabled={busy !== null || specChangedAfterAudit}
              disabledNote={specChangedAfterAudit ? 're-audit the edited spec first' : undefined}
            />
            {draft.mode === 'mapped' ? (
              <View style={styles.pathBlock}>
                <Text style={styles.pathLabel}>Existing valid spec paths</Text>
                {coverage.valid_spec_paths.length === 0 ? (
                  <Text style={styles.auditReview}>No supported mapping target exists in this draft.</Text>
                ) : (
                  <View style={styles.pathRow}>
                    {coverage.valid_spec_paths.map((path) => {
                      const selected = draft.selected_paths.includes(path);
                      return (
                        <Pressable
                          key={path}
                          disabled={busy !== null || specChangedAfterAudit}
                          onPress={() => onDraftChange(component.component_id, {
                            ...draft,
                            mode: 'mapped',
                            selected_paths: selected
                              ? draft.selected_paths.filter((item) => item !== path)
                              : [...draft.selected_paths, path],
                          })}
                          style={[styles.pathChip, selected && styles.pathChipSelected]}>
                          <Text style={[styles.pathText, selected && styles.pathTextSelected]}>
                            {path}
                          </Text>
                        </Pressable>
                      );
                    })}
                  </View>
                )}
              </View>
            ) : (
              <Field
                label="Why this visible component is still unresolved"
                value={draft.unresolved_note}
                onChange={(unresolved_note) => {
                  if (busy !== null || specChangedAfterAudit) return;
                  onDraftChange(component.component_id, {
                    ...draft,
                    mode: 'unresolved',
                    unresolved_note,
                  });
                }}
                multiline
                placeholder="State what the plate cannot establish or which supported spec/form definition is missing."
              />
            )}
            {componentBlockers.map((blocker) => (
              <Text key={blocker.code} style={styles.blocker}>
                {blocker.message} Next: {blocker.required_resolution}
              </Text>
            ))}
          </View>
        );
      })}
      <Text style={styles.blockerSummary}>
        Remaining source-coverage blockers: {coverage.blockers.length}
      </Text>
      {auditPassed ? (
        <Notice
          kind="ok"
          text="Independent component accounting passed with no remaining coverage blockers. Measurements and manufacturing geometry still require designer confirmation."
        />
      ) : (
        <Notice
          kind="info"
          text={`Independent audit: ${viewLabel(coverage.audit.status)}. Project creation remains blocked until the audit passes with zero source-coverage blockers.`}
        />
      )}
      <View style={styles.actions}>
        <Button
          title={busy === 'apply' ? 'Applying component decisions…' : 'Apply component decisions'}
          disabled={busy !== null || specChangedAfterAudit || !draftsValid
            || resolutions.length === 0}
          onPress={onApply}
        />
        <Button
          title={busy === 'audit' ? 'Auditing source coverage…' : 'Re-run independent source audit'}
          kind="ghost"
          disabled={busy !== null || coverage.components.length === 0}
          onPress={onAudit}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 8 },
  heading: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 15,
    marginBottom: 8,
  },
  componentCard: {
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: 12,
    padding: 10,
    marginBottom: 10,
    backgroundColor: theme.paper,
  },
  componentId: { color: theme.ink, fontSize: 13, fontWeight: '600' },
  description: { color: theme.ink, fontSize: 13, lineHeight: 19, marginTop: 4 },
  meta: { color: theme.faint, fontSize: 11, marginTop: 4 },
  currentMapping: { color: theme.accent, fontSize: 12, marginTop: 6 },
  auditPass: { color: theme.ok, fontSize: 12, marginTop: 5 },
  auditReview: { color: theme.danger, fontSize: 12, marginTop: 5 },
  pathBlock: { marginBottom: 10 },
  pathLabel: { color: theme.faint, fontSize: 12, marginBottom: 5 },
  pathRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 5 },
  pathChip: {
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  pathChipSelected: { backgroundColor: theme.ink, borderColor: theme.ink },
  pathText: { color: theme.ink, fontSize: 11 },
  pathTextSelected: { color: theme.paper },
  blocker: { color: theme.danger, fontSize: 11, lineHeight: 16, marginTop: 5 },
  blockerSummary: { color: theme.ink, fontSize: 12, marginBottom: 8 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' },
});
