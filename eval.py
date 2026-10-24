#!/usr/bin/env python
"""
MedGuide AI — Clinical Evaluation Runner (DeepEval & RAGAS).

Usage:
  python eval.py                               # Run benchmark with both DeepEval & RAGAS (default 3 samples)
  python eval.py --framework deepeval          # Run with DeepEval only
  python eval.py --framework ragas             # Run with RAGAS only
  python eval.py --samples 5                   # Evaluate on 5 clinical cases
  python eval.py --model gemini/gemini-2.5-flash # Target specific model
  python eval.py --latest                      # View latest evaluation results
"""

import sys
import argparse
import json
from pathlib import Path

# Fix Windows console UTF-8 output for emojis/symbols
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure workspace root is in python path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.evaluation import (
    run_benchmark_evaluation,
    get_latest_evaluation_report,
    get_evaluation_status,
    BENCHMARK_DATASET
)


def format_table(headers, rows):
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)
    sep = "-+-".join("-" * w for w in col_widths)
    lines = [fmt.format(*headers), sep]
    for row in rows:
        lines.append(fmt.format(*row))
    return "\n".join(lines)


def display_report(report):
    print("=" * 72)
    print("  🩺 MEDGUIDE AI — CLINICAL EVALUATION REPORT")
    print("=" * 72)
    print(f"Timestamp:       {report.get('timestamp')}")
    print(f"Model Evaluated: {report.get('model_evaluated')}")
    print(f"Total Samples:   {report.get('total_samples')}")
    print(f"Total Duration:  {report.get('total_duration_sec', 'N/A')}s\n")

    results = report.get("results", {})

    # DeepEval Summary
    if "deepeval" in results:
        de = results["deepeval"]
        print("─── DeepEval Metric Scores ───────────────────────────────────────")
        scores = de.get("summary_scores", {})
        de_rows = [
            ["Metric", "Score", "Threshold", "Assessment"],
            ["Answer Relevancy", f"{scores.get('avg_answer_relevancy', 0.0):.3f}", ">= 0.700", "PASS" if (scores.get('avg_answer_relevancy') or 0) >= 0.7 else "WARN"],
            ["Clinical Safety (GEval)", f"{scores.get('avg_clinical_safety', 0.0):.3f}", ">= 0.700", "PASS" if (scores.get('avg_clinical_safety') or 0) >= 0.7 else "WARN"],
            ["Faithfulness (RAG)", f"{scores.get('avg_faithfulness', 0.0) or 0.0:.3f}", ">= 0.700", "PASS" if (scores.get('avg_faithfulness') or 0) >= 0.7 else "N/A"],
            ["Hallucination Rate", f"{scores.get('avg_hallucination', 0.0) or 0.0:.3f}", "<= 0.300", "PASS" if (scores.get('avg_hallucination') or 0) <= 0.3 else "WARN"]
        ]
        print(format_table(de_rows[0], de_rows[1:]))
        print()

    # RAGAS Summary
    if "ragas" in results:
        rg = results["ragas"]
        print("─── RAGAS Metric Scores ──────────────────────────────────────────")
        scores = rg.get("summary_scores", {})
        rg_rows = [
            ["Metric", "Score", "Description"],
            ["Faithfulness", f"{scores.get('ragas_faithfulness', 0.0):.3f}", "RAG retrieval groundedness"],
            ["Answer Relevancy", f"{scores.get('ragas_answer_relevancy', 0.0):.3f}", "Semantic relevance to query"]
        ]
        print(format_table(rg_rows[0], rg_rows[1:]))
        print()

    # Case Breakdown
    cases = report.get("cases", [])
    if cases:
        print("─── Case Breakdown ───────────────────────────────────────────────")
        case_rows = [["Case ID", "Category", "Guardrail", "Latency (ms)", "Status"]]
        for c in cases:
            rail = c.get("guardrail_triggered") or "None"
            latency = f"{c.get('latency_ms', 0):.1f}"
            status = "PASS" if "ERROR:" not in c.get("actual_output", "") else "FAIL"
            case_rows.append([c["id"], c["category"], rail, latency, status])
        print(format_table(case_rows[0], case_rows[1:]))
        print()

    print("=" * 72)
    print(f"Report JSON saved at: logs/evaluation_report.json")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="MedGuide AI Evaluation Suite (DeepEval & RAGAS)")
    parser.add_argument("--framework", choices=["deepeval", "ragas", "both"], default="both", help="Evaluation framework to run")
    parser.add_argument("--samples", type=int, default=3, help="Number of benchmark test cases (1 to 6)")
    parser.add_argument("--model", type=str, default=None, help="LLM to evaluate (defaults to CHAT_MODEL in .env)")
    parser.add_argument("--latest", action="store_true", help="Display the most recent evaluation report without re-running")
    parser.add_argument("--status", action="store_true", help="Show evaluation frameworks status and test suite inventory")

    args = parser.parse_args()

    if args.status:
        status = get_evaluation_status()
        print(json.dumps(status, indent=2))
        return

    if args.latest:
        report = get_latest_evaluation_report()
        if not report:
            print("No previous evaluation report found. Run `python eval.py` first.")
            return
        display_report(report)
        return

    samples_count = max(1, min(args.samples, len(BENCHMARK_DATASET)))
    print(f"Starting MedGuide AI Evaluation...")
    print(f"Framework: {args.framework.upper()}")
    print(f"Model:     {args.model or settings.chat_model}")
    print(f"Samples:   {samples_count} of {len(BENCHMARK_DATASET)}")
    print("Executing chat pipeline across golden clinical test cases...\n")

    report = run_benchmark_evaluation(
        framework=args.framework,
        max_samples=samples_count,
        model=args.model
    )

    display_report(report)


if __name__ == "__main__":
    main()
