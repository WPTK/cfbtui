# Before/after scoreboard pairs

Hand-edited ESPN scoreboard payloads for store tests. Each `<kind>_before.json` / `<kind>_after.json` is a
minimal scoreboard (`leagues`, `week`, one event). A test parses both with the scoreboard parser and diffs
before to after. These are data only; nothing here is generated at test time.

Base event: `401856717`, Texas at Oklahoma ("TEX VS OU"), taken from `../scoreboard_20261010_final.json`.
TEX is away (team 251, ranked 1), OU is home (team 201, curatedRank 99 = unranked). Real final: TEX 24, OU 27.
The event is trimmed (links, highlights, headlines, leaders, geoBroadcasts, notes, linescores, statistics,
winner removed); status and `situation` are edited per file. `final_after` restores `winner` on competitors.
`ranked_upset_watch` sets TEX rank 5 and OU rank 12 in both files.

| kind | before | after |
|---|---|---|
| touchdown | Q2 10:35, TEX 7 OU 7, reception | Q2 10:09, TEX 14 OU 7, passing TD (+7) |
| field_goal | Q2 0:40, TEX 14 OU 7, red zone | Q2 0:12, TEX 17 OU 7, FG good (+3) |
| safety | Q3 8:14, TEX 17 OU 7 | Q3 7:50, TEX 17 OU 9, safety (+2 OU) |
| two_point | Q4 14:48, TEX 17 OU 15, OU rushing TD | Q4 14:48, TEX 17 OU 17, 2-pt good |
| pat | Q4 6:32, TEX 23 OU 24, TEX TD | Q4 6:32, TEX 24 OU 24, XP good |
| game_start | scheduled, 0-0 | Q1 15:00, 0-0, kickoff |
| period_change | Q1 0:00, TEX 7 OU 0 | Q2 15:00, TEX 7 OU 0 |
| halftime | Q2 0:00, TEX 17 OU 7 | halftime, TEX 17 OU 7 |
| second_half | halftime, TEX 17 OU 7 | Q3 15:00, TEX 17 OU 7, kickoff |
| red_zone | Q3 10:56, TEX 17 OU 7, OU at TEX 28 | Q3 10:20, TEX 17 OU 7, OU at TEX 17, red zone |
| upset_watch | Q4 10:30, TEX 17 OU 17 | Q4 10:07, TEX 17 OU 24, OU pick-six |
| final | Q4 0:00, TEX 24 OU 27 | final, TEX 24 OU 27, OU winner |
| multi_score | Q2 10:35, TEX 7 OU 7 | Q2 0:12, TEX 17 OU 7 (+10 jump, FG lastPlay: ambiguous) |
| score_correction | Q3 5:00, TEX 20 OU 7 | Q3 4:50, TEX 17 OU 7 (-3 reversal: a correction) |
| ranked_upset_watch | as upset_watch, both ranked (5 vs 12) | OU 24, TEX 17 |
| favorite_leads | Q4 10:30, TEX 17 OU 17 | Q4 10:07, TEX 24 OU 17 (#1 leads unranked: no upset watch) |
