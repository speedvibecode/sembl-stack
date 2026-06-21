export const feedbackStatuses = ["open", "planned", "closed"] as const;
export const feedbackPriorities = ["low", "medium", "high"] as const;

export type FeedbackStatus = (typeof feedbackStatuses)[number];
export type FeedbackPriority = (typeof feedbackPriorities)[number];

export type FeedbackItem = {
  id: string;
  title: string;
  body: string;
  status: FeedbackStatus;
  priority: FeedbackPriority;
  created_at: string;
  user_id: string | null;
};

export const statusLabels: Record<FeedbackStatus, string> = {
  open: "Open",
  planned: "Planned",
  closed: "Closed",
};

export const priorityLabels: Record<FeedbackPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

export const fallbackFeedback: FeedbackItem[] = [
  {
    id: "demo-1",
    title: "Invite review needs a status trail",
    body: "The current flow accepts an invite, but there is no visible state once the request is queued.",
    status: "open",
    priority: "high",
    created_at: "2026-06-20T12:00:00.000Z",
    user_id: null,
  },
  {
    id: "demo-2",
    title: "Export filter should persist",
    body: "After returning from a detail page, the board should keep the selected status filter.",
    status: "planned",
    priority: "medium",
    created_at: "2026-06-20T12:10:00.000Z",
    user_id: null,
  },
  {
    id: "demo-3",
    title: "Closed cards need calmer contrast",
    body: "Resolved items should remain readable without competing with open items.",
    status: "closed",
    priority: "low",
    created_at: "2026-06-20T12:20:00.000Z",
    user_id: null,
  },
];
