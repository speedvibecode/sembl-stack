import { MessagesSquare } from "lucide-react";

import { AuthPanel } from "@/components/auth-panel";
import { FeedbackBoard } from "@/components/feedback-board";
import { FeedbackForm } from "@/components/feedback-form";
import {
  fallbackFeedback,
  type FeedbackItem,
  type FeedbackStatus,
} from "@/lib/feedback";
import { createSupabaseServerClient } from "@/lib/supabase/server";

type PageData = {
  configured: boolean;
  signedIn: boolean;
  email: string | null;
  items: FeedbackItem[];
};

async function loadPageData(): Promise<PageData> {
  const supabase = await createSupabaseServerClient();

  if (!supabase) {
    return {
      configured: false,
      signedIn: false,
      email: null,
      items: fallbackFeedback,
    };
  }

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return {
      configured: true,
      signedIn: false,
      email: null,
      items: [],
    };
  }

  const { data, error } = await supabase
    .from("feedback_items")
    .select("id,title,body,status,priority,created_at,user_id")
    .order("created_at", { ascending: false })
    .limit(50);

  return {
    configured: true,
    signedIn: true,
    email: user.email ?? null,
    items: error ? [] : (data as FeedbackItem[]),
  };
}

const countByStatus = (items: FeedbackItem[], status: FeedbackStatus) =>
  items.filter((item) => item.status === status).length;

export default async function Home() {
  const data = await loadPageData();
  const total = data.items.length;
  const open = countByStatus(data.items, "open");
  const planned = countByStatus(data.items, "planned");
  const closed = countByStatus(data.items, "closed");

  return (
    <main className="app-shell">
      <aside className="side-panel" aria-label="Feedback controls">
        <div className="brand-row">
          <span className="brand-mark" aria-hidden="true">
            <MessagesSquare size={22} />
          </span>
          <div>
            <h1>Feedback Board</h1>
            <p>Vercel and Supabase flagship</p>
          </div>
        </div>

        <div className="metric-grid" aria-label="Feedback totals">
          <div className="metric">
            <strong>{total}</strong>
            <p>Total</p>
          </div>
          <div className="metric">
            <strong>{open}</strong>
            <p>Open</p>
          </div>
          <div className="metric">
            <strong>{planned}</strong>
            <p>Planned</p>
          </div>
          <div className="metric">
            <strong>{closed}</strong>
            <p>Closed</p>
          </div>
        </div>

        <AuthPanel
          configured={data.configured}
          signedIn={data.signedIn}
          email={data.email}
        />

        <FeedbackForm configured={data.configured} signedIn={data.signedIn} />
      </aside>

      <section className="main-panel" aria-label="Feedback items">
        <div className="top-bar">
          <div>
            <h2>Board inbox</h2>
            <p>
              Signed-in users see and manage only their own feedback through
              Supabase row level security.
            </p>
          </div>
        </div>

        <FeedbackBoard items={data.items} signedIn={data.signedIn} />
      </section>
    </main>
  );
}
