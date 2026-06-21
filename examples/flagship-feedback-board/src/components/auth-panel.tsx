"use client";

import { LogOut, Mail, Send } from "lucide-react";
import { useState } from "react";

import { createSupabaseBrowserClient } from "@/lib/supabase/client";

type AuthPanelProps = {
  configured: boolean;
  signedIn: boolean;
  email: string | null;
};

export function AuthPanel({ configured, signedIn, email }: AuthPanelProps) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");

  async function requestMagicLink(formData: FormData) {
    setPending(true);
    setMessage("");

    const supabase = createSupabaseBrowserClient();
    const nextEmail = String(formData.get("email") ?? "").trim();

    if (!supabase || !nextEmail) {
      setMessage("Enter an email after Supabase is configured.");
      setPending(false);
      return;
    }

    const { error } = await supabase.auth.signInWithOtp({
      email: nextEmail,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    setMessage(error ? error.message : "Check your email.");
    setPending(false);
  }

  async function signOut() {
    setPending(true);
    const supabase = createSupabaseBrowserClient();
    await supabase?.auth.signOut();
    window.location.reload();
  }

  return (
    <section className="auth-panel" aria-label="Authentication">
      <h3>Access</h3>
      {!configured ? (
        <div className="setup-note">
          <strong>Supabase env missing</strong>
          <span>NEXT_PUBLIC_SUPABASE_URL and publishable key are required.</span>
        </div>
      ) : signedIn ? (
        <div className="form-grid">
          <p className="auth-copy">{email ?? "Signed in"}</p>
          <button
            className="button secondary"
            type="button"
            onClick={signOut}
            disabled={pending}
          >
            <LogOut size={16} aria-hidden="true" />
            Sign out
          </button>
        </div>
      ) : (
        <form action={requestMagicLink}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              placeholder="name@example.com"
              required
            />
          </div>
          <button className="button primary" type="submit" disabled={pending}>
            {pending ? (
              <Mail size={16} aria-hidden="true" />
            ) : (
              <Send size={16} aria-hidden="true" />
            )}
            Send link
          </button>
          {message ? <p className="form-message">{message}</p> : null}
        </form>
      )}
    </section>
  );
}
