import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Api } from './api';
import { Button, Field, Notice, Section } from './components';
import { Pin, SheetView } from './SheetView';
import { theme } from './theme';

/** The factory's view: open a share link, see one unambiguous version, pin comments. */
export function ShareScreen({ api, token: initialToken }: { api: Api; token: string | null }) {
  const [token, setToken] = useState(initialToken ?? '');
  const [shared, setShared] = useState<any | null>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [author, setAuthor] = useState('Factory');
  const [pendingPin, setPendingPin] = useState<{ x: number; y: number } | null>(null);
  const [commentBody, setCommentBody] = useState('');
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  useEffect(() => {
    if (initialToken) {
      setToken(initialToken);
      open(initialToken);
    }
  }, [initialToken]);

  const open = async (t: string) => {
    setNotice(null);
    const r = await api.openShare(t);
    if (!r.ok) {
      setNotice({ kind: 'error', text: 'Unknown share link.' });
      setShared(null);
      return;
    }
    setShared(r.body);
    const sheet = await api.shareSheet(t);
    setSvg(sheet.ok ? sheet.body : null);
  };

  const submitComment = async () => {
    if (!pendingPin || !commentBody) return;
    const r = await api.shareComment(token, {
      author,
      view: 'sheet',
      x_pct: pendingPin.x,
      y_pct: pendingPin.y,
      body: commentBody,
    });
    if (r.ok) {
      setShared({ ...shared, comments: [...shared.comments, r.body] });
      setPendingPin(null);
      setCommentBody('');
      setNotice({ kind: 'ok', text: 'Comment pinned — the designer sees it on this exact version.' });
    } else {
      setNotice({ kind: 'error', text: r.status === 403 ? 'This link is view-only.' : 'Could not comment.' });
    }
  };

  const pins: Pin[] = (shared?.comments ?? []).map((c: any, i: number) => ({
    x_pct: c.x_pct,
    y_pct: c.y_pct,
    label: String(i + 1),
  }));
  if (pendingPin) pins.push({ x_pct: pendingPin.x, y_pct: pendingPin.y, label: '+' });

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Section title="Open a share link">
        <Field label="Token" value={token} onChange={setToken} placeholder="paste share token" />
        <Button title="Open" onPress={() => open(token)} disabled={!token} />
      </Section>

      {shared && (
        <>
          <Notice
            kind="info"
            text={`${shared.design_id} — version ${shared.version}, permanently this state (${shared.scope} access).`}
          />
          {svg && (
            <Section title="Technical sheet — tap to pin a comment">
              <SheetView svg={svg} pins={pins} onPin={(x, y) => setPendingPin({ x, y })} />
              {pendingPin && (
                <View style={{ marginTop: 8 }}>
                  <Field label="Your name" value={author} onChange={setAuthor} />
                  <Field
                    label={`Comment at ${pendingPin.x}%, ${pendingPin.y}%`}
                    value={commentBody}
                    onChange={setCommentBody}
                    multiline
                  />
                  <Button title="Pin comment" onPress={submitComment} disabled={!commentBody} />
                </View>
              )}
            </Section>
          )}
          {shared.comments.length > 0 && (
            <Section title="Comments">
              {shared.comments.map((c: any, i: number) => (
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
        </>
      )}
      {notice && <Notice kind={notice.kind} text={notice.text} />}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 12 },
  comment: { fontSize: 13, color: theme.ink, marginBottom: 8 },
  commentNum: { fontWeight: 'bold', color: theme.danger },
  commentMeta: { fontSize: 11, color: theme.faint },
});
