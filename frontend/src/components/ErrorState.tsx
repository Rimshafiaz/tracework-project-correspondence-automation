import { Link } from "react-router";

export function ErrorState({
  title,
  message,
  onRetry,
  backToProjects = false,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
  backToProjects?: boolean;
}) {
  return (
    <div className="message-state" role="alert">
      <h2>{title}</h2>
      <p>{message}</p>
      <div className="message-actions">
        {onRetry ? (
          <button className="secondary-button" type="button" onClick={onRetry}>
            Try again
          </button>
        ) : null}
        {backToProjects ? <Link to="/projects">Back to projects</Link> : null}
      </div>
    </div>
  );
}
