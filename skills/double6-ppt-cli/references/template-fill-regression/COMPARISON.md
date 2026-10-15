# Template-fill v48 vs pm6 (0.4.0-exp.3, 14 sets, 2026-10-15)

Specs T2 (slide 3 body) and T10 (slide 2 body, slide 5 headers) were shortened: their exp.2 texts are now blocked by plan check (overflow even at the floor / >1.6x, or running into the slide-3 table in T2), as PowerPoint would overflow them.

| template | backend | status | id_preservation | slots_replaced | slots_pPr_kept | slots_paragraphs_ok | slots_placeholder_kept | lo_found | lo_contained | lo_overflow_max_ratio | notes_ok | transitions_ok | mixed_kept |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 | v48 | ok | 1.0 | 20 | 20 | 18 | 20 | 20 | 20 | 0 | 0 | 0 | 0 |
| T1 | pm6 | ok | 1.0 | 20 | 20 | 20 | 20 | 20 | 20 | 0 | 0 | 0 | 0 |
| T2 | v48 | ok | 1.0 | 27 | 27 | 26 | 27 | 15 | 13 | 0.765 | 0 | 0 | 0 |
| T2 | pm6 | ok | 1.0 | 27 | 27 | 27 | 27 | 16 | 14 | 0.498 | 0 | 0 | 0 |
| T3 | v48 | ok | 1.0 | 53 | 53 | 50 | 7 | 49 | 49 | 0 | 0 | 0 | 0 |
| T3 | pm6 | ok | 1.0 | 53 | 53 | 53 | 7 | 49 | 49 | 0 | 0 | 0 | 0 |
| T4 | v48 | ok | 1.0 | 17 | 17 | 15 | 7 | 16 | 15 | 0.137 | 0 | 0 | 0 |
| T4 | pm6 | ok | 1.0 | 17 | 17 | 17 | 7 | 17 | 17 | 0 | 0 | 0 | 0 |
| T5 | v48 | ok | 1.0 | 17 | 17 | 17 | 0 | 17 | 17 | 0 | 0 | 0 | 0 |
| T5 | pm6 | ok | 1.0 | 17 | 17 | 17 | 0 | 17 | 17 | 0 | 0 | 0 | 0 |
| T6 | v48 | ok | 1.0 | 10 | 10 | 10 | 9 | 10 | 10 | 0 | 5 | 3 | 1 |
| T6 | pm6 | ok | 1.0 | 10 | 10 | 10 | 9 | 10 | 10 | 0 | 5 | 3 | 1 |
| T7 | v48 | ok | 1.0 | 13 | 13 | 13 | 12 | 10 | 8 | 2.099 | 6 | 1 | 1 |
| T7 | pm6 | ok | 1.0 | 13 | 13 | 13 | 12 | 10 | 8 | 2.099 | 6 | 1 | 1 |
| T8 | v48 | ok | 1.0 | 9 | 9 | 9 | 8 | 8 | 6 | 0.45 | 4 | 1 | 1 |
| T8 | pm6 | ok | 1.0 | 9 | 9 | 9 | 8 | 8 | 6 | 0.45 | 4 | 1 | 1 |
| T9 | v48 | ok | 1.0 | 4 | 4 | 4 | 4 | 4 | 4 | 0 | 2 | 0 | 0 |
| T9 | pm6 | ok | 1.0 | 4 | 4 | 4 | 4 | 4 | 4 | 0 | 2 | 0 | 0 |
| T10 | v48 | ok | 1.0 | 28 | 28 | 23 | 25 | 27 | 23 | 0.749 | 11 | 3 | 1 |
| T10 | pm6 | ok | 1.0 | 28 | 28 | 28 | 25 | 28 | 28 | 0 | 11 | 3 | 1 |
| T11 | v48 | ok | 1.0 | 6 | 6 | 6 | 6 | 6 | 6 | 0 | 4 | 1 | 0 |
| T11 | pm6 | ok | 1.0 | 6 | 6 | 6 | 6 | 6 | 6 | 0 | 4 | 1 | 0 |
| T3X | v48 | ok | 1.0 | 53 | 53 | 50 | 7 | 49 | 49 | 0 | 0 | 0 | 0 |
| T3X | pm6 | ok | 1.0 | 53 | 53 | 53 | 7 | 48 | 48 | 0 | 0 | 0 | 0 |
| T5L | v48 | ok | 1.0 | 17 | 17 | 17 | 0 | 17 | 17 | 0 | 0 | 0 | 0 |
| T5L | pm6 | ok | 1.0 | 17 | 17 | 17 | 0 | 17 | 17 | 0 | 0 | 0 | 0 |
| T4X | v48 | ok | 1.0 | 17 | 17 | 15 | 7 | 16 | 14 | 2.474 | 0 | 0 | 0 |
| T4X | pm6 | check_failed |  |  |  |  |  |  |  |  |  |  |  |
