#!/usr/bin/env python
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from apps.transactions.money import parse_decimal_to_minor  # noqa: E402
from classification.confidence import normalize_merchant  # noqa: E402
from classification.langchain_adapter import LangChainCategorizerAdapter  # noqa: E402

CATEGORIES = (
    "SOFTWARE",
    "OFFICE_SUPPLIES",
    "TRANSPORT",
    "MEALS",
    "UTILITIES",
    "PROFESSIONAL_SERVICES",
    "MARKETING",
    "EDUCATION",
    "EQUIPMENT",
    "SUBSCRIPTIONS",
    "INCOME",
    "TRANSFER",
    "UNCATEGORIZED",
)


def compute_macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> float:
    f1s: list[float] = []
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p != label)
        if tp == 0 and fp == 0 and fn == 0:
            continue
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        f1s.append(f1)
    return sum(f1s) / len(f1s) if f1s else 0.0


def evaluate() -> None:
    root = Path(__file__).resolve().parent.parent
    gt_path = root / "fixtures" / "ground_truth.csv"
    sha_path = root / "fixtures" / "ground_truth.sha256"

    expected_sha = sha_path.read_text(encoding="utf-8").strip().split()[0]
    actual_sha = hashlib.sha256(gt_path.read_bytes()).hexdigest()
    assert expected_sha == actual_sha, "ground_truth.csv SHA-256 mismatch!"

    with gt_path.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))

    # Split deterministically by merchant_family (1/3 held-out families, zero family overlap with dev)
    families = sorted({r["merchant_family"] for r in rows})
    held_out_families = {fam for idx, fam in enumerate(families) if idx % 3 == 0}
    dev_rows = [r for r in rows if r["merchant_family"] not in held_out_families]
    held_out_rows = [r for r in rows if r["merchant_family"] in held_out_families]

    adapter = LangChainCategorizerAdapter(allowed_categories=CATEGORIES)

    def run_pass(dataset: list[dict], prior_rules: dict[str, str]):
        y_true: list[str] = []
        y_pred: list[str] = []
        review_flags: list[bool] = []
        user_rule_hits = 0
        confusion: dict[str, Counter] = defaultdict(Counter)

        for r in dataset:
            amt_minor = parse_decimal_to_minor(r["signed_amount"], currency=r["currency"])
            out = adapter.classify(
                description=r["description"],
                amount_minor=amt_minor,
                merchant_rules=prior_rules,
            )
            if out.category_source == "USER_RULE":
                user_rule_hits += 1
            truth = r["true_category"]
            y_true.append(truth)
            y_pred.append(out.category_code)
            review_flags.append(out.review_status == "NEEDS_REVIEW")
            confusion[truth][out.category_code] += 1
        return y_true, y_pred, review_flags, user_rule_hits, confusion

    # Pass 1: Cold first-pass on held-out merchant families (no prior merchant corrections)
    y_true, y_pred, reviews, _, confusion = run_pass(held_out_rows, {})
    correct = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p)
    acc = correct / len(held_out_rows)
    abstention_rate = sum(1 for fl in reviews if fl) / len(held_out_rows)
    macro_f1 = compute_macro_f1(y_true, y_pred, list(CATEGORIES))

    # Post-review correctness when uncertain (<0.700) items are reviewed accurately
    post_review_correct = sum(
        1 for t, p, is_rev in zip(y_true, y_pred, reviews, strict=True) if is_rev or t == p
    )
    post_review_acc = post_review_correct / len(held_out_rows)

    # Pass 2: Simulate remembering merchant corrections approved during Pass 1 review -> measure 2nd import lift!
    learned_rules: dict[str, str] = {}
    for r, is_rev in zip(held_out_rows, reviews, strict=True):
        if is_rev:
            learned_rules[normalize_merchant(r["description"])] = r["true_category"]

    y_true_2, y_pred_2, _, rule_hits_2, _ = run_pass(held_out_rows, learned_rules)
    second_import_acc = sum(1 for t, p in zip(y_true_2, y_pred_2, strict=True) if t == p) / len(
        held_out_rows
    )

    out_dir = root / "evidence" / "categorization"
    out_dir.mkdir(parents=True, exist_ok=True)
    pub_ev = root / "frontend" / "public" / "evidence"
    pub_ev.mkdir(parents=True, exist_ok=True)

    report = {
        "datasetSha256": actual_sha,
        "totalRows": len(rows),
        "devRows": len(dev_rows),
        "heldOutRows": len(held_out_rows),
        "heldOutFamiliesCount": len(held_out_families),
        "classification": "REPRODUCED",
        "historicalResumeClaimFirstPassAccuracy": "0.850 (HISTORICAL_RESUME_CLAIM)",
        "heldOutFirstPassAccuracy": round(acc, 4),
        "heldOutMacroF1": round(macro_f1, 4),
        "abstentionRate": round(abstention_rate, 4),
        "postReviewAccuracy": round(post_review_acc, 4),
        "correctionsConsultedCount": len(learned_rules),
        "secondImportUserRuleHits": rule_hits_2,
        "secondImportRememberedAccuracy": round(second_import_acc, 4),
    }

    (out_dir / "eval-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (pub_ev / "eval-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # Confusion matrix markdown
    md_lines = [
        "# SoloLedger Held-Out Classification Evaluation",
        "",
        f"- **Dataset SHA-256**: `{actual_sha}`",
        f"- **Split**: Disjoint by `merchant_family` ({len(held_out_families)} held-out families / {len(held_out_rows)} held-out transactions; {len(dev_rows)} dev transactions)",
        f"- **Held-out first-pass accuracy (`REPRODUCED`)**: `{acc:.4f}` ({correct}/{len(held_out_rows)})",
        f"- **Historical resume claim**: `~85%` (`HISTORICAL_RESUME_CLAIM` — local lexicon + mock provider is reported honestly below)",
        f"- **Held-out macro F1**: `{macro_f1:.4f}`",
        f"- **Abstention / `<0.700` review rate**: `{abstention_rate:.4f}` ({sum(reviews)}/{len(held_out_rows)})",
        f"- **Post-review accuracy**: `{post_review_acc:.4f}`",
        f"- **Second-import accuracy with {len(learned_rules)} remembered rules (`{rule_hits_2}` rule hits)**: `{second_import_acc:.4f}`",
        "",
        "## Per-Category Held-Out Confusion Counts (`truth -> predicted: count`)",
        "",
    ]
    for truth_cat in sorted(confusion.keys()):
        dist = ", ".join(f"{pred}: {cnt}" for pred, cnt in sorted(confusion[truth_cat].items()))
        md_lines.append(f"- **{truth_cat}**: {dist}")

    (out_dir / "confusion-matrix.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    evaluate()

