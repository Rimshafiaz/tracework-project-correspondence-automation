export function AppLoading({ label }: { label: string }) {
  return (
    <main className="app-loading" aria-busy="true" aria-label={label}>
      <span className="loading-line loading-line-short" />
      <span className="loading-line" />
      <span className="loading-line" />
    </main>
  );
}

export function TableLoading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="loading-table" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, index) => (
        <div className="loading-row" key={index}>
          <span className="loading-line loading-line-code" />
          <span className="loading-line" />
          <span className="loading-line loading-line-status" />
        </div>
      ))}
    </div>
  );
}
