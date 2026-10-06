import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { AppLoading } from "../components/LoadingState";
import { useAuth } from "./authContext";

export function LoginPage() {
  const { session, isLoading, signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const destination =
    (location.state as { from?: string } | null)?.from ?? "/projects";

  if (isLoading) return <AppLoading label="Restoring session" />;
  if (session) return <Navigate to="/projects" replace />;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await signIn(email.trim(), password);
      navigate(destination, { replace: true });
    } catch {
      setError("Unable to sign in with those credentials.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-brand-panel" aria-label="Tracework">
        <p className="login-wordmark">Tracework</p>
        <div className="login-statement"><h1>Correspondence becomes evidence-backed project state.</h1><p>Tracework interprets incoming project communication, preserves the evidence, and holds unsafe changes for operator review.</p></div>
        <p className="login-footnote">Internal operator workspace</p>
      </section>
      <section className="login-form-panel" aria-labelledby="login-title">
        <div className="login-panel">
          <p className="login-kicker">Operator access</p>
          <h2 id="login-title">Sign in to Tracework</h2>
          <p className="login-subtitle">Use the approved account provisioned for this workspace.</p>

          <form className="login-form" onSubmit={handleSubmit}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder="operator@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            placeholder="Enter password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />

          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}

          <button className="primary-button" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Signing in" : "Sign in"}
          </button>
          </form>
          <div className="login-access-note"><strong>No public signup.</strong><span>Operator accounts are provisioned outside Tracework.</span><span>Gmail and Drive authorization are configured separately from this sign-in.</span></div>
        </div>
      </section>
    </main>
  );
}
