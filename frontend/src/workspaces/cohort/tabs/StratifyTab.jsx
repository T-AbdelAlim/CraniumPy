import { useMemo, useState } from "react";
import { columnType, describe, distinctValues, groupNumericByBins, groupNumericByCategory } from "../lib/stats.js";
import { downloadCohortExportXlsx, runStatsTest } from "../../../api/cohort.js";
import BoxPlot from "../charts/BoxPlot.jsx";
import InfoTooltip from "../../../components/InfoTooltip.jsx";

const TEST_EXPLAINER =
  "2 groups: Welch's t-test (doesn't assume equal variance) alongside Mann-Whitney U (rank-based, no " +
  "normality assumption). 3+ groups: one-way ANOVA alongside Kruskal-Wallis H, the same pairing one level up, " +
  "followed by every pair compared (Tukey HSD and Dunn's test, corrected for the number of pairs) to show which " +
  "groups differ from which. " +
  "both come back together deliberately - which to trust depends on sample size and how skewed the data " +
  "actually looks, not something this workspace can decide for you.";

// why each test was picked (purely mechanical - see api/routers/cohort.py's
// _run_stats_test, which only ever looks at the group count, never the
// data's actual shape) + a link to the real scipy documentation for anyone
// who wants the exact assumptions/formula. deliberately outside
// InfoTooltip (plain text only, no links) - this needs a real clickable
// reference.
const TEST_INFO = {
  "Welch's t-test": {
    reason:
      "run because exactly 2 groups were compared. Welch's t-test tests whether the two groups' means differ, " +
      "without assuming they have equal variance (the safer default over a plain Student's t-test).",
    docsUrl: "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html",
  },
  "Mann-Whitney U": {
    reason:
      "the rank-based counterpart run alongside Welch's t-test - tests whether one group tends to have larger " +
      "values than the other, without assuming the data is normally distributed (some statistical power is " +
      "traded away for that, versus the t-test, when the data actually is close to normal).",
    docsUrl: "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html",
  },
  "One-way ANOVA": {
    reason:
      "run because 3 or more groups were compared. tests whether at least one group's mean differs from the " +
      "others, assuming the groups are roughly normally distributed with similar variance.",
    docsUrl: "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.f_oneway.html",
  },
  "Kruskal-Wallis H": {
    reason:
      "the rank-based counterpart run alongside one-way ANOVA - the same question (does at least one group " +
      "differ), without the normal-distribution/equal-variance assumption.",
    docsUrl: "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kruskal.html",
  },
};

const PAIRWISE_INFO = {
  "Tukey HSD": {
    reason:
      "follows the ANOVA: compares every pair of group means, with p-values corrected so the chance of any false " +
      "positive over all pairs stays at 5%.",
    docsUrl: "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.tukey_hsd.html",
  },
  "Dunn (Holm)": {
    reason:
      "follows Kruskal-Wallis: compares every pair on the same ranks, without assuming normal data; p-values " +
      "Holm-corrected for the number of pairs.",
    docsUrl: "https://doi.org/10.1080/00401706.1964.10490181",
  },
};

const formatP = (p) => (p < 0.0001 ? "< 0.0001" : p.toFixed(4));

const TEST_DISCLAIMER =
  "Which test ran was picked automatically from the number of groups alone, not from your data's actual sample " +
  "size, distribution shape, or independence between observations. Please verify yourself that the test shown " +
  "is actually appropriate for your comparison before drawing conclusions from the result.";

// a sensible default "group by" column - prefers "diagnosis" (the primary
// stratification variable this app's own domain cares about) when it's
// there, otherwise the first categorical column that actually splits the
// cohort into more than one group and fewer groups than there are rows
// (an id-like column such as cohort_id/file_name is unique per row, so
// "grouping" by it would just produce one useless n=1 group per patient -
// a real default has to skip those rather than picking the first column
// in the sheet regardless of whether it's usable).
function defaultGroupByColumn(rows, columns, types) {
  if (columns.includes("diagnosis")) return "diagnosis";
  for (const c of columns) {
    if (types[c] !== "categorical") continue;
    const n = distinctValues(rows, c).length;
    if (n > 1 && n < rows.length) return c;
  }
  return columns[0] || "";
}

// pick a numeric metric + a column to stratify by (categorical as-is, or a
// numeric column split into equal-width bins), see per-group descriptive
// stats and a box plot instantly (client-side), then optionally run a real
// inferential test against the backend (scipy.stats - see api/cohort.js).
export default function StratifyTab({ rows, columns }) {
  const types = useMemo(() => Object.fromEntries(columns.map((c) => [c, columnType(rows, c)])), [rows, columns]);
  const numericColumns = columns.filter((c) => types[c] === "numeric");

  const [metricColumn, setMetricColumn] = useState(numericColumns[0] || "");
  const [groupByColumn, setGroupByColumn] = useState(() => defaultGroupByColumn(rows, columns, types));
  const [nBins, setNBins] = useState(4);
  const [testResult, setTestResult] = useState(null);
  const [testStatus, setTestStatus] = useState("");
  const [exportStatus, setExportStatus] = useState("");

  const groupByIsNumeric = groupByColumn && types[groupByColumn] === "numeric";

  // a test result belongs to one comparison: clear it when that changes
  function changeComparison(setter) {
    return (value) => {
      setter(value);
      setTestResult(null);
      setTestStatus("");
    };
  }

  const groups = useMemo(() => {
    if (!metricColumn || !groupByColumn) return {};
    return groupByIsNumeric
      ? groupNumericByBins(rows, groupByColumn, metricColumn, nBins)
      : groupNumericByCategory(rows, groupByColumn, metricColumn);
  }, [rows, metricColumn, groupByColumn, groupByIsNumeric, nBins]);

  const groupLabels = Object.keys(groups).filter((label) => groups[label].length > 0);

  async function handleRunTest() {
    setTestResult(null);
    setTestStatus("running...");
    try {
      const values = Object.fromEntries(groupLabels.map((label) => [label, groups[label]]));
      const result = await runStatsTest(values);
      setTestResult(result);
      setTestStatus("");
    } catch (err) {
      setTestStatus(`failed: ${err.message}`);
    }
  }

  async function handleExport() {
    setExportStatus("exporting...");
    try {
      const statsRows = groupLabels.map((label) => {
        const s = describe(groups[label]);
        return {
          group: label,
          n: String(s.n),
          mean: s.mean?.toFixed(2) ?? "",
          median: s.median?.toFixed(2) ?? "",
          sd: s.sd !== null ? s.sd.toFixed(2) : "",
          iqr: s.iqr !== null ? s.iqr.toFixed(2) : "",
        };
      });
      const sheets = [
        { title: "descriptive stats", columns: ["group", "n", "mean", "median", "sd", "iqr"], rows: statsRows },
      ];
      if (testResult) {
        sheets.push({
          title: "test result",
          columns: ["test", "statistic", "p_value"],
          rows: [
            { test: testResult.test_name, statistic: testResult.statistic.toFixed(4), p_value: testResult.p_value.toFixed(4) },
            {
              test: testResult.alternative_test_name,
              statistic: testResult.alternative_statistic.toFixed(4),
              p_value: testResult.alternative_p_value.toFixed(4),
            },
          ],
        });
        if (testResult.pairwise?.length) {
          sheets.push({
            title: "pairwise",
            columns: ["group_a", "group_b", "mean_difference", testResult.pairwise_test_name, testResult.alternative_pairwise_test_name],
            rows: testResult.pairwise.map((pr) => ({
              group_a: pr.group_a,
              group_b: pr.group_b,
              mean_difference: pr.mean_difference.toFixed(4),
              [testResult.pairwise_test_name]: pr.p_value.toFixed(4),
              [testResult.alternative_pairwise_test_name]: pr.alternative_p_value.toFixed(4),
            })),
          });
        }
      }
      await downloadCohortExportXlsx(sheets, `${metricColumn}_by_${groupByColumn}.xlsx`);
      setExportStatus("");
    } catch (err) {
      setExportStatus(`export failed: ${err.message}`);
    }
  }

  if (numericColumns.length === 0) {
    return <p className="hint">No numeric columns to compare yet - load a cohort with some measurements first.</p>;
  }

  return (
    <section>
      <label htmlFor="stratify-metric">compare</label>
      <select id="stratify-metric" value={metricColumn} onChange={(e) => changeComparison(setMetricColumn)(e.target.value)}>
        {numericColumns.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>

      <label htmlFor="stratify-groupby">group by</label>
      <select id="stratify-groupby" value={groupByColumn} onChange={(e) => changeComparison(setGroupByColumn)(e.target.value)}>
        {columns.map((c) => (
          <option key={c} value={c}>{c} {types[c] === "numeric" ? "(numeric)" : ""}</option>
        ))}
      </select>

      {groupByIsNumeric && (
        <>
          <label htmlFor="stratify-bins">number of bins</label>
          <input
            id="stratify-bins"
            type="number"
            min="2"
            max="10"
            value={nBins}
            onChange={(e) => changeComparison(setNBins)(Math.max(2, Math.min(10, Number(e.target.value) || 2)))}
          />
        </>
      )}

      {groupLabels.length === 0 ? (
        <p className="hint">Not enough data for this comparison.</p>
      ) : (
        <>
          <table className="measurements-table cohort-ws-table cohort-ws-stats-table">
            <thead>
              <tr>
                <th>group</th>
                <th>n</th>
                <th>mean</th>
                <th>median</th>
                <th>SD</th>
                <th>IQR</th>
              </tr>
            </thead>
            <tbody>
              {groupLabels.map((label) => {
                const s = describe(groups[label]);
                return (
                  <tr key={label}>
                    <td className="cohort-ws-col-name">{label}</td>
                    <td>{s.n}</td>
                    <td>{s.mean?.toFixed(2)}</td>
                    <td>{s.median?.toFixed(2)}</td>
                    <td>{s.sd !== null ? s.sd.toFixed(2) : "-"}</td>
                    <td>{s.iqr !== null ? s.iqr.toFixed(2) : "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <BoxPlot groups={groups} />

          <button type="button" className="button-subtle" onClick={handleExport}>
            export to Excel
          </button>
          {exportStatus && <p className="status-line">{exportStatus}</p>}

          <button
            type="button"
            onClick={handleRunTest}
            disabled={groupLabels.length < 2 || groupLabels.some((l) => groups[l].length < 2)}
          >
            run statistical test
            <InfoTooltip text={TEST_EXPLAINER} />
          </button>
          {testStatus && <p className="status-line">{testStatus}</p>}
          {testResult && (
            <>
              <table className="measurements-table cohort-ws-table">
                <tbody>
                  <tr>
                    <th>{testResult.test_name}</th>
                    <td>statistic {testResult.statistic.toFixed(3)}, p = {testResult.p_value.toFixed(4)}</td>
                  </tr>
                  <tr>
                    <th>{testResult.alternative_test_name}</th>
                    <td>statistic {testResult.alternative_statistic.toFixed(3)}, p = {testResult.alternative_p_value.toFixed(4)}</td>
                  </tr>
                </tbody>
              </table>
              {testResult.pairwise?.length > 0 && <PairwiseResult result={testResult} />}
              {[
                testResult.test_name,
                testResult.alternative_test_name,
              ].map((name) => (
                <p key={name} className="hint">
                  <strong>{name}</strong>: {TEST_INFO[name]?.reason}{" "}
                  <a href={TEST_INFO[name]?.docsUrl} target="_blank" rel="noreferrer">scipy documentation</a>
                </p>
              ))}
              {testResult.n_groups > 2 &&
                [testResult.pairwise_test_name, testResult.alternative_pairwise_test_name].map((name) => (
                  <p key={name} className="hint">
                    <strong>{name}</strong>: {PAIRWISE_INFO[name]?.reason}{" "}
                    <a href={PAIRWISE_INFO[name]?.docsUrl} target="_blank" rel="noreferrer">reference</a>
                  </p>
                ))}
              <p className="hint cohort-ws-test-disclaimer">{TEST_DISCLAIMER}</p>
            </>
          )}
        </>
      )}
    </section>
  );
}

// which groups differ from which: every pair, both p-values, the significant
// ones marked, and a one-line summary above the table
function PairwiseResult({ result }) {
  const { alpha, pairwise, pairwise_test_name: name, alternative_pairwise_test_name: altName } = result;
  const both = pairwise.filter((p) => p.p_value < alpha && p.alternative_p_value < alpha);
  const onlyOne = pairwise.filter((p) => (p.p_value < alpha) !== (p.alternative_p_value < alpha));
  const pairText = (p) => `${p.group_a} vs ${p.group_b}`;
  return (
    <>
      <p className="cohort-ws-pairwise-summary">
        {both.length === 0
          ? `No pair of groups differs significantly in both tests (p < ${alpha}).`
          : `Significantly different (p < ${alpha} in both tests): ${both.map(pairText).join(", ")}.`}
        {onlyOne.length > 0 && ` Significant in one test only: ${onlyOne.map(pairText).join(", ")}.`}
      </p>
      <table className="measurements-table cohort-ws-table cohort-ws-stats-table">
        <thead>
          <tr>
            <th>pair</th>
            <th>difference in means</th>
            <th>{name} p</th>
            <th>{altName} p</th>
          </tr>
        </thead>
        <tbody>
          {pairwise.map((p) => (
            <tr key={pairText(p)}>
              <td className="cohort-ws-col-name">{pairText(p)}</td>
              <td>{p.mean_difference >= 0 ? "+" : ""}{p.mean_difference.toFixed(2)}</td>
              <td className={p.p_value < alpha ? "cohort-ws-significant" : ""}>{formatP(p.p_value)}</td>
              <td className={p.alternative_p_value < alpha ? "cohort-ws-significant" : ""}>{formatP(p.alternative_p_value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">difference in means: second group minus first. Significant p-values (below {alpha}) in bold.</p>
    </>
  );
}
