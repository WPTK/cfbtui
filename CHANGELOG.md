# Simulation Log

Release notes for cfbtui, kept the way a fortress overseer keeps a journal. Newest first. Versions follow FibVer.

## 0.3.0 (2026-10-12)

- An EspnClient was hired to knock on ESPN's door. When the door answers with a 5xx it waits, doubles its patience, and knocks again. When it answers with a 4xx it goes home at once.
- The client learned to carry a User-Agent with its name and version on it, in case anyone asks.
- Eleven dataclasses moved into `cfbtui/espn/models.py` and froze themselves solid. None of them has been mutated since.
- The parsers were told that every key may be missing and believed it. All 108 games in the saved fixtures passed through without a single exception. The parsers found this anticlimactic.
- Rank 99 has been recognised as a polite way of saying "unranked" and is now `None`. Rank 0 received the same treatment.
- A GameStore took up residence in `cfbtui/state/` and now remembers every game it has ever seen, including the ones that vanish from the feed and return later pretending nothing happened.
- The store learned to read ESPN's `lastPlay` and name a score correctly: touchdown, field goal, safety, two-point conversion, extra point. When the play does not explain the points, it guesses the likeliest combination and marks the guess with a question mark.
- A six-point touchdown now leaves a conversion pending. A bare two points afterward is a two-point try; a bare two points otherwise is a safety. The store feels strongly about this.
- A score going *down* is no longer a negative touchdown. It is a ScoreCorrected event, and it is embarrassed.
- An UpsetRule was written. It knows that an unranked team leading a ranked one is a watch, that the same thing at the final whistle is an upset, and that a tie is nothing at all. When the scoreboard forgets a team's rank it asks the AP poll.
- On first sight of a live game the store now announces what it sees: kickoff, halftime, red zone, upset watch. Final games on first sight are left alone; they have had enough attention.
- Sixteen before/after fixture pairs were hand-carved from the Texas-Oklahoma game and filed under `tests/fixtures/pairs/`. Texas loses in every one that reaches the end.
- A spot-check script was left in `scripts/` for the next Saturday. It fetches twice, thirty seconds apart, and prints whatever the store says happened.
- The live check ran on a Monday and found 62 games, all pregame, zero errors and nothing to report. It reported this.
- A code review arrived with eight findings. All eight were fixed, including a lastPlay with no team on it that had been trying to take credit for both sides' points.
- One hundred sixty-two tests. The founders have stopped running them twice.

## 0.2.0 (2026-10-12)

- Founded a repository in an empty directory on a Sunday afternoon. It had no commits and no opinions.
- Chose Python and Textual. A Go binary was considered and politely declined.
- Painted six team colors on the wall to see whether Windows Terminal could tell them apart. It could.
- Hired a StatusBar. It has learned to tell the time and announce the version. It does nothing else and seems content.
- Set the version to 0.1.0 and told it that it would only ever advance by Fibonacci numbers. It accepted this without complaint.
- A pre-commit hook took up residence in `.githooks/` and now bumps the patch number on every commit. It cannot be reasoned with.
- A commit-msg hook moved in beside it. It refuses any commit that is not a poem with its form declared. Several test messages were turned away at the door.
- A pre-push hook stands at the gate and inspects every outgoing commit for a `Poetic-Form:` trailer. So far it has admitted everyone.
- Fetched four payloads from ESPN and stored them under `tests/fixtures/` as evidence: a pregame week, a finished Saturday, the rankings, and one Texas game in full.
- Wrote twenty tests. All twenty passed. The founders were suspicious and ran them again. They passed again.
- Caught carriage returns creeping into the hook scripts on the way to other machines. Posted a `.gitattributes` to keep every line ending as LF. The hooks have stopped falling silent.
- Held a code review. Seven findings arrived at the gate; five were let inside. The `tanku` spelling is now accepted. The status bar no longer says "Eastern Daylight Time" in full.
- Made the repository public under the MIT license and pushed it to GitHub. The README carries a disclaimer about ESPN that nobody will read.
- The scoreboard has not been built. The games go on without it.
