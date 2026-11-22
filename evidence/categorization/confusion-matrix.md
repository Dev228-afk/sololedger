# SoloLedger Held-Out Classification Evaluation

- **Dataset SHA-256**: `e85b3b6d2b2298cc85a40e25971b1830927e8c3f85d8c6669cccbf8170ad1565`
- **Split**: Disjoint by `merchant_family` (13 held-out families / 338 held-out transactions; 742 dev transactions)
- **Held-out first-pass accuracy (`REPRODUCED`)**: `0.9320` (315/338)
- **Historical resume claim**: `~85%` (`HISTORICAL_RESUME_CLAIM` — local lexicon + mock provider is reported honestly below)
- **Held-out macro F1**: `0.8729`
- **Abstention / `<0.700` review rate**: `0.2219` (75/338)
- **Post-review accuracy**: `1.0000`
- **Second-import accuracy with 3 remembered rules (`75` rule hits)**: `1.0000`

## Per-Category Held-Out Confusion Counts (`truth -> predicted: count`)

- **EDUCATION**: EDUCATION: 49
- **EQUIPMENT**: EQUIPMENT: 31
- **INCOME**: INCOME: 31
- **MARKETING**: MARKETING: 33
- **OFFICE_SUPPLIES**: OFFICE_SUPPLIES: 56
- **PROFESSIONAL_SERVICES**: PROFESSIONAL_SERVICES: 31, UNCATEGORIZED: 23
- **SOFTWARE**: SOFTWARE: 26
- **SUBSCRIPTIONS**: SUBSCRIPTIONS: 19
- **TRANSPORT**: TRANSPORT: 39
