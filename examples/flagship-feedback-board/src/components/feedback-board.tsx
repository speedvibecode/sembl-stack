"use client";

import { CheckCircle2, CircleDot, Clock3, ListFilter } from "lucide-react";
import { useMemo, useState } from "react";

import { updateFeedbackStatus } from "@/app/actions";
import {
  feedbackStatuses,
  statusLabels,
  type FeedbackItem,
  type FeedbackStatus,
} from "@/lib/feedback";

type View = "all" | FeedbackStatus;

type FeedbackBoardProps = {
  items: FeedbackItem[];
  signedIn: boolean;
};

const views: { id: View; label: string }[] = [
  { id: "all", label: "All" },
  { id: "open", label: statusLabels.open },
  { id: "planned", label: statusLabels.planned },
  { id: "closed", label: statusLabels.closed },
];

const statusIcon = {
  open: CircleDot,
  planned: Clock3,
  closed: CheckCircle2,
};

export function FeedbackBoard({ items, signedIn }: FeedbackBoardProps) {
  const [view, setView] = useState<View>("all");

  const visibleItems = useMemo(
    () => (view === "all" ? items : items.filter((item) => item.status === view)),
    [items, view],
  );

  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Feedback</h3>
        <span className="pill open">
          <ListFilter size={14} aria-hidden="true" />
          {visibleItems.length}
        </span>
      </div>

      <div className="tabs" role="tablist" aria-label="Feedback views">
        {views.map((nextView) => (
          <button
            key={nextView.id}
            className="tab"
            type="button"
            role="tab"
            aria-selected={view === nextView.id}
            onClick={() => setView(nextView.id)}
          >
            {nextView.label}
          </button>
        ))}
      </div>

      {visibleItems.length === 0 ? (
        <div className="empty-state">No feedback in this view.</div>
      ) : (
        <div className="feedback-list">
          {visibleItems.map((item) => (
            <article className="feedback-item" key={item.id}>
              <div className="item-topline">
                <div>
                  <h4 className="item-title">{item.title}</h4>
                  <p className="item-body">{item.body}</p>
                </div>
                <div className="pill-row" aria-label="Item metadata">
                  <StatusPill status={item.status} />
                  <span className={`pill priority-${item.priority}`}>
                    {item.priority}
                  </span>
                </div>
              </div>

              <div className="status-actions" aria-label="Status actions">
                {feedbackStatuses.map((status) => (
                  <form
                    action={updateFeedbackStatus.bind(null, item.id, status)}
                    key={status}
                  >
                    <button
                      type="submit"
                      aria-current={item.status === status}
                      disabled={!signedIn || item.status === status}
                    >
                      {statusLabels[status]}
                    </button>
                  </form>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function StatusPill({ status }: { status: FeedbackStatus }) {
  const Icon = statusIcon[status];

  return (
    <span className={`pill ${status}`}>
      <Icon size={14} aria-hidden="true" />
      {statusLabels[status]}
    </span>
  );
}
