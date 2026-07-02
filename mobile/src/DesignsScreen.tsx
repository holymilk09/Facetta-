import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Api } from './api';
import { Button, ChipRow, Field, Notice, Section } from './components';
import { Pin, SheetView } from './SheetView';
import { theme } from './theme';

export function DesignsScreen({
  api,
  designer,
  focusDesignId,
  onEdit,
  onOpenShare,
}: {
  api: Api;
  designer: string;
  focusDesignId: string | null;
  onEdit: (designId: string, version: number, spec: any) => void;
  onOpenShare: (token: string) => void;
}) {
  const [designs, setDesigns] = useState<any[]>([]);
  const [selected, setSelected] = useState<string | null>(focusDesignId);
  const [detail, setDetail] = useState<any | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [spec, setSpec] = useState<any | null>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [comments, setComments] = useState<any[]>([]);
  const [shareLink, setShareLink] = useState<any | null>(null);
  const [pendingPin, setPendingPin] = useState<{ x: number; y: number } | null>(null);
  const [commentBody, setCommentBody] = useState('');
  const [notice, setNotice] = useState<string | null>(null);

  const refreshList = () => api.listDesigns().then((r) => r.ok && setDesigns(r.body.designs));

  useEffect(() => {
    refreshList();
  }, [api.baseUrl]);

  useEffect(() => {
    if (focusDesignId) openDesign(focusDesignId);
  }, [focusDesignId]);

  const openDesign = async (id: string) => {
    setSelected(id);
    setShareLink(null);
    setPendingPin(null);
    const r = await api.getDesign(id);
    if (!r.ok) return;
    setDetail(r.body);
    const latest = r.body.versions[r.body.versions.length - 1].version;
    openVersion(id, latest);
  };

  const openVersion = async (id: string, v: number) => {
    setVersion(v);
    setPendingPin(null);
    const [specRes, sheetRes, commentsRes] = await Promise.all([
      api.getVersionSpec(id, v),
      api.getSheet(id, v),
      api.listComments(id, v),
    ]);
    if (specRes.ok) setSpec(specRes.body);
    setSvg(sheetRes.ok ? sheetRes.body : null);
    if (commentsRes.ok) setComments(commentsRes.body.comments);
  };

  const createShare = async () => {
    if (!selected || version == null) return;
    const r = await api.createShare(selected, version, 'comment');
    if (r.ok) setShareLink(r.body);
  };

  const submitComment = async () => {
    if (!selected || version == null || !pendingPin || !commentBody) return;
    const r = await api.addComment(selected, version, {
      author: designer,
      view: 'sheet',
      x_pct: pendingPin.x,
      y_pct: pendingPin.y,
      body: commentBody,
    });
    if (r.ok) {
      setComments([...comments, r.body]);
      setPendingPin(null);
      setCommentBody('');
      setNotice('Comment pinned.');
    }
  };

  const pins: Pin[] = comments.map((c, i) => ({ x_pct: c.x_pct, y_pct: c.y_pct, label: String(i + 1) }));
  if (pendingPin) pins.push({ x_pct: pendingPin.x, y_pct: pendingPin.y, label: '+' });

  if (!selected || !detail) {
    return (
      <ScrollView contentContainerStyle={styles.content}>
        <Section title="Designs">
          {designs.length === 0 && <Text style={styles.hint}>No designs yet — build one in the Builder tab.</Text>}
          {designs.map((d) => (
            <Pressable key={d.design_id} style={styles.designRow} onPress={() => openDesign(d.design_id)}>
              <Text style={styles.designId}>{d.design_id}</Text>
              <Text style={styles.designMeta}>
                v{d.latest_version} · {d.created_by}
              </Text>
            </Pressable>
          ))}
          <Button title="Refresh" kind="ghost" onPress={refreshList} />
        </Section>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Button title="← All designs" kind="ghost" onPress={() => { setSelected(null); setDetail(null); refreshList(); }} />
      <Section title={detail.design_id}>
        <ChipRow
          label="Version (immutable — every edit is a new one)"
          options={detail.versions.map((v: any) => v.version)}
          value={version}
          onSelect={(v) => openVersion(detail.design_id, v)}
          render={(v) => `v${v}`}
        />
        {spec && (
          <Text style={styles.specSummary}>
            {spec.stone.carat} ct {spec.stone.species}, {spec.stone.cut.replace(/_/g, ' ')} ·{' '}
            {spec.stone.color.trade} · {spec.metal.karat ? `${spec.metal.karat}k ` : ''}
            {spec.metal.color} {spec.metal.material}
            {spec.ring_size ? ` · US ${spec.ring_size.value}` : ''}
          </Text>
        )}
        <View style={styles.actions}>
          <Button
            title="Edit (new version)"
            kind="ghost"
            onPress={() => spec && onEdit(detail.design_id, version ?? 1, spec)}
          />
          <Button title="Create share link" kind="ghost" onPress={createShare} />
        </View>
        {shareLink && (
          <View>
            <Notice kind="ok" text={`Share link (pinned to v${shareLink.version}): ${api.baseUrl}${shareLink.path}`} />
            <Button title="Open as factory →" kind="ghost" onPress={() => onOpenShare(shareLink.token)} />
          </View>
        )}
      </Section>

      {svg && (
        <Section title="Technical sheet — tap to pin a comment">
          <SheetView svg={svg} pins={pins} onPin={(x, y) => setPendingPin({ x, y })} />
          {pendingPin && (
            <View style={{ marginTop: 8 }}>
              <Field
                label={`Comment at ${pendingPin.x}%, ${pendingPin.y}%`}
                value={commentBody}
                onChange={setCommentBody}
                multiline
              />
              <View style={styles.actions}>
                <Button title="Pin comment" onPress={submitComment} disabled={!commentBody} />
                <Button title="Cancel" kind="ghost" onPress={() => setPendingPin(null)} />
              </View>
            </View>
          )}
        </Section>
      )}

      {comments.length > 0 && (
        <Section title="Comments">
          {comments.map((c, i) => (
            <Text key={c.id} style={styles.comment}>
              <Text style={styles.commentNum}>{i + 1}.</Text> {c.body}
              {'\n'}
              <Text style={styles.commentMeta}>
                {c.author} · {c.view} @ {c.x_pct}%, {c.y_pct}%
              </Text>
            </Text>
          ))}
        </Section>
      )}
      {notice && <Notice kind="ok" text={notice} />}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 12 },
  designRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: theme.line,
  },
  designId: { fontFamily: theme.serif, fontSize: 15, color: theme.ink },
  designMeta: { fontSize: 13, color: theme.faint },
  specSummary: { fontSize: 13, color: theme.ink, marginBottom: 8 },
  actions: { flexDirection: 'row', flexWrap: 'wrap' },
  hint: { fontSize: 13, color: theme.faint, fontStyle: 'italic', marginBottom: 8 },
  comment: { fontSize: 13, color: theme.ink, marginBottom: 8 },
  commentNum: { fontWeight: 'bold', color: theme.danger },
  commentMeta: { fontSize: 11, color: theme.faint },
});
