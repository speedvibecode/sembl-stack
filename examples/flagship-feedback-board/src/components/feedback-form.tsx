"use client";

import { Plus, Send } from "lucide-react";
import { useActionState } from "react";

import { createFeedback, type CreateFeedbackState } from "@/app/actions";
import { priorityLabels } from "@/lib/feedback";

const initialState: CreateFeedbackState = {
  status: "idle",
  message: "",
};

export function FeedbackForm({
  configured,
  signedIn,
}: {
  configured: boolean;
  signedIn: boolean;
}) {
  const [state, formAction, pending] = useActionState(
    createFeedback,
    initialState,
  );
  const disabled = pending || !configured || !signedIn;

  return (
    <form className="feedback-form" action={formAction}>
      <h3>New feedback</h3>
      <div className="field">
        <label htmlFor="title">Title</label>
        <input
          id="title"
          name="title"
          minLength={3}
          placeholder="CSV export stalls"
          disabled={disabled}
          required
        />
      </div>

      <div className="field">
        <label htmlFor="body">Note</label>
        <textarea
          id="body"
          name="body"
          minLength={10}
          placeholder="What happened, where, and what result was expected?"
          disabled={disabled}
          required
        />
      </div>

      <div className="field">
        <label htmlFor="priority">Priority</label>
        <select id="priority" name="priority" disabled={disabled} defaultValue="medium">
          <option value="low">{priorityLabels.low}</option>
          <option value="medium">{priorityLabels.medium}</option>
          <option value="high">{priorityLabels.high}</option>
        </select>
      </div>

      <button className="button primary" type="submit" disabled={disabled}>
        {pending ? <Send size={16} aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />}
        Add
      </button>

      {!configured ? (
        <p className="field-hint">Configure Supabase to enable writes.</p>
      ) : !signedIn ? (
        <p className="field-hint">Sign in to add feedback.</p>
      ) : null}

      {state.message ? (
        <p className={`form-message ${state.status}`}>{state.message}</p>
      ) : null}
    </form>
  );
}
