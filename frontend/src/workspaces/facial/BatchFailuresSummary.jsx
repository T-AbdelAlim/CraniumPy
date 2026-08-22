// a consolidated "here's what got excluded and why" report once a batch
// finishes - the per-file topology/load QC itself already happens server-
// side, one file at a time, never aborting the batch (see
// api/routers/facial.py's _process_one_mesh, which validates each mesh's
// topology against the template independently). before this component, the
// only way to discover a failure was paging through BatchReviewPanel one
// file at a time and reading ExportPanel's own bare success count - this
// surfaces every excluded file up front instead.
export default function BatchFailuresSummary({ results }) {
  const failed = results.filter((r) => r.status === "error");
  if (failed.length === 0) return null;

  return (
    <div className="facial-batch-failures-summary">
      <p className="hint">
        {failed.length} file{failed.length === 1 ? "" : "s"} excluded:
      </p>
      <ul>
        {failed.map((r) => (
          <li key={r.filename}>
            <strong>{r.filename}</strong>: {r.error}
          </li>
        ))}
      </ul>
    </div>
  );
}
