import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { approveReplyDraft, editReplyDraft, getReplyDraft, rejectReplyDraft, sendReplyDraft } from "../../api/replyDrafts";
import { queryKeys } from "../../api/queryKeys";
import { ErrorState } from "../../components/ErrorState";
import { TableLoading } from "../../components/LoadingState";
import { StatusBadge } from "../../components/StatusBadge";
import { queryClient } from "../../lib/queryClient";

export function ReplyDraftDetailPage() {
  const { draftId = "" } = useParams();
  const detail = useQuery({ queryKey: queryKeys.replyDraft(draftId), queryFn: () => getReplyDraft(draftId), enabled: Boolean(draftId) });
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.replyDraft(draftId) });
    if (detail.data) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectReplyDrafts(detail.data.project_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectActivity(detail.data.project_id) });
    }
  };
  const edit = useMutation({ mutationFn: () => editReplyDraft(draftId, { subject, body }), onSuccess: () => { setEditing(false); void refresh(); } });
  const approve = useMutation({ mutationFn: () => approveReplyDraft(draftId), onSuccess: refresh });
  const reject = useMutation({ mutationFn: () => rejectReplyDraft(draftId), onSuccess: refresh });
  const send = useMutation({ mutationFn: () => sendReplyDraft(draftId), onSuccess: refresh });

  if (detail.isPending) return <TableLoading rows={3} />;
  if (detail.isError || !detail.data) return <ErrorState title={detail.error instanceof ApiError && detail.error.kind === "not_found" ? "Reply draft not found" : "Reply draft could not be loaded"} message="This draft is not available." backToProjects />;
  const draft = detail.data;
  const busy = edit.isPending || approve.isPending || reject.isPending || send.isPending;
  return <article className="reply-draft-detail">
    <Link className="back-link" to={`/projects/${draft.project_id}`}>Project</Link>
    <header className="project-header"><h1>Reply draft</h1><StatusBadge status={draft.status} /></header>
    <dl className="project-context-register"><div><dt>Reply type</dt><dd>{draft.reply_type.replaceAll("_", " ")}</dd></div><div><dt>Recipient</dt><dd>{draft.recipient_email ?? "Unavailable"}</dd></div><div><dt>Follow-up</dt><dd>{draft.follow_up_id}</dd></div><div><dt>Source correspondence</dt><dd>{draft.source_correspondence_event_id ?? "Unavailable"}</dd></div></dl>
    {draft.send_attention_required ? <p className="empty-state">Send requires attention: {draft.send_failure_code ?? "review configuration or source lineage"}.</p> : null}
    {draft.status === "SEND_PENDING" ? <p className="empty-state">Send is pending recovery. Refresh before attempting another action.</p> : null}
    <section className="workspace-section"><h2>Current reply</h2>{editing ? <><label>Subject<input value={subject} onChange={(event) => setSubject(event.target.value)} /></label><label>Body<textarea value={body} onChange={(event) => setBody(event.target.value)} rows={10} /></label><button className="primary-button" disabled={busy || !subject.trim() || !body.trim()} onClick={() => edit.mutate()}>Save edit</button><button className="secondary-button" disabled={busy} onClick={() => { setEditing(false); setSubject(draft.effective.subject); setBody(draft.effective.body); }}>Cancel</button></> : <><h3>{draft.effective.subject}</h3><p className="reply-draft-body">{draft.effective.body}</p></>}</section>
    <section className="workspace-section"><h2>Generated original</h2><h3>{draft.generated.subject}</h3><p className="reply-draft-body">{draft.generated.body}</p></section>
    <div className="action-row">{draft.can_edit ? <button className="secondary-button" disabled={busy} onClick={() => { setSubject(draft.effective.subject); setBody(draft.effective.body); setEditing(true); }}>Edit</button> : null}{draft.can_approve ? <button className="primary-button" disabled={busy} onClick={() => approve.mutate()}>Approve</button> : null}{draft.can_reject ? <button className="secondary-button" disabled={busy} onClick={() => reject.mutate()}>Reject</button> : null}{draft.can_send || draft.can_retry_send ? <button className="primary-button" disabled={busy} onClick={() => send.mutate()}>{draft.can_retry_send ? "Retry send" : "Send"}</button> : null}</div>
  </article>;
}
