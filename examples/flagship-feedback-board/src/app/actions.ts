"use server";

import { revalidatePath } from "next/cache";

import {
  feedbackPriorities,
  feedbackStatuses,
  type FeedbackPriority,
  type FeedbackStatus,
} from "@/lib/feedback";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export type CreateFeedbackState = {
  status: "idle" | "success" | "error";
  message: string;
};

const initialError = (message: string): CreateFeedbackState => ({
  status: "error",
  message,
});

const isFeedbackPriority = (value: string): value is FeedbackPriority =>
  feedbackPriorities.includes(value as FeedbackPriority);

const isFeedbackStatus = (value: string): value is FeedbackStatus =>
  feedbackStatuses.includes(value as FeedbackStatus);

export async function createFeedback(
  _state: CreateFeedbackState,
  formData: FormData,
): Promise<CreateFeedbackState> {
  const title = String(formData.get("title") ?? "").trim();
  const body = String(formData.get("body") ?? "").trim();
  const rawPriority = String(formData.get("priority") ?? "medium");
  const priority = isFeedbackPriority(rawPriority) ? rawPriority : "medium";

  if (title.length < 3) {
    return initialError("Use a title with at least 3 characters.");
  }

  if (body.length < 10) {
    return initialError("Use a note with at least 10 characters.");
  }

  const supabase = await createSupabaseServerClient();
  if (!supabase) {
    return initialError("Supabase environment variables are not configured.");
  }

  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();

  if (userError || !user) {
    return initialError("Sign in before adding feedback.");
  }

  const { error } = await supabase.from("feedback_items").insert({
    title,
    body,
    priority,
    status: "open",
    user_id: user.id,
  });

  if (error) {
    return initialError(error.message);
  }

  revalidatePath("/");
  return { status: "success", message: "Feedback added." };
}

export async function updateFeedbackStatus(
  id: string,
  status: FeedbackStatus,
): Promise<void> {
  if (!id || !isFeedbackStatus(status)) {
    return;
  }

  const supabase = await createSupabaseServerClient();
  if (!supabase) {
    return;
  }

  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();

  if (userError || !user) {
    return;
  }

  await supabase
    .from("feedback_items")
    .update({ status })
    .eq("id", id)
    .eq("user_id", user.id);

  revalidatePath("/");
}
