# Simulation Log

Release notes for cfbtui, kept the way a fortress overseer keeps a journal. Newest first. Versions follow FibVer.

## 0.5.0 (2026-10-12)

- The hello-world swatches were taken down from the wall. A scoreboard was hung in their place, and nobody asked where the swatches went.
- Sixty-two GameCards moved in, each wearing its teams' colors. The first attempt wore none. The background had been politely overruled by the room it was standing in, and a test was hired to notice this sort of thing.
- A card learned to say what is happening to it: the clock, the possession arrow, the timeouts as little dots, the down and distance, and a border title that shouts UPSET WATCH or RED ZONE when either is true.
- Cards flash when someone scores. The flash lasts three seconds, which the cards consider generous.
- A Ticker took the bottom of the screen and writes down every event the store emits, newest last. It never once consulted `str(event)`. It has its own opinions about touchdowns.
- A glyph table was founded at last, with four sets: ascii, unicode, emoji and nerd. Nerd was chosen as the default after a vote of one. Pressing `g` cycles them, and the ticker rewrites its whole history in the new alphabet without complaint.
- A PollScheduler was given the job of asking ESPN what happened. It asks every 20 seconds while anything is live and every 5 minutes when nothing is. It also learned to wake up for a kickoff, because sleeping through one was found to be embarrassing.
- When ESPN fails to answer, the scheduler keeps the last good cards on the wall, doubles its patience up to two minutes, and tells the status bar. When ESPN returns, the touchdowns scored during the outage are announced late and without apology.
- "Stale" was defined after some argument. It means no successful fetch lately. It does not mean nothing changed. A ten-minute halftime of identical polls was found to be perfectly fresh and rather boring.
- The status bar learned to say "updated 12s ago", "next 8s", "STALE" and "ERROR showing data 1m04s old". It turns red when it means it.
- A GameStore handed to the scheduler was discovered to be falsy while empty, and was quietly replaced by a different GameStore. Sixty-two games arrived and found nobody home. It was fixed and a test now stands guard.
- Kickoff times are now Eastern, with no leading zero on the hour. A tzdata package was hired for Windows, which does not carry its own.
- A code review arrived with ten findings. Seven were fixed, including a flash aimed at a card that had not yet been born. Three were written down for another day.
- Two hundred sixty-one tests. The founders pulled the network cable on a live scoreboard and watched sixty-two cards stay exactly where they were.

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

## 0.2.3 (2026-10-12)

- The phase handoff was discovered to be a link. A link is not a prompt. Whoever needed it had to go and fetch it.
- The rule now says the session's final message must paste the entire next prompt into the chat, in one code block. The file is merely the archived copy and has been told so.
- Step seven of the phase-end ritual grew a clause: "then paste the full next prompt into the chat." It is now the last thing anyone does.

## 0.2.2 (2026-10-12)

- The Phase 1 handoff announced that the repo was at version 0.2.0. The repo had already moved on without it, as repos do.
- The handoff now says 0.2.x and instructs the next session to ask the program itself. The program knows. It always knows.

## 0.2.1 (2026-10-12)

- The changelog was found to be a wall of prose with no door in it. Bullets were installed and light came in.
- The release-notes rule in CLAUDE.md was rewritten to demand one event per bullet, and to forbid prose paragraphs and plain "Added X" lists.
- The sample entry in the rules received blank lines and dashes of its own. UpsetRule is still obsessed with South Carolina in it.
- The whole 0.2.0 section was walked out of its paragraphs and into bullets. It went quietly.

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

## 0.1.2 (2026-10-12)

- The reviewer spoke. Seven findings arrived at the gate and five were let inside.
- The hooks went looking for Python and found only the Windows Store alias stub, which opens a store instead of a program. They now try the `py` launcher first, then `python`, and exit with a complaint if neither will answer.
- The hooks stopped wrapping the Python command in quotes, because it may be `py -3`, which is two words and had been taken for one.
- The poem checker learned that "tanku" is a perfectly good way to spell tanka. It had been turning tanku away at the door.
- A blank line between two trailers no longer hides the `Poetic-Form:` from the checker. It was there the whole time.
- A poem line with a colon in it ("halftime: the band plays") is no longer mistaken for a trailer. The poets were relieved.
- A warning was added to the rules: `git commit --amend` runs the hook again and burns another Fibonacci number. That is the price.
- The status bar dropped its timezone name and moved to a 24-hour clock. Nobody asked it to; it seems calmer.
- The build was told it needs setuptools 77 or newer. It had been getting by on 69 and was not consulted.
- Three new tests were hired to watch the poem checker: one for tanku, one for the blank line, one for the colons.

## 0.1.1 (2026-10-12)

- Carriage returns were found creeping into the hook scripts on fresh clones. The shell fell silent whenever it met one.
- A `.gitattributes` was posted at the door: every line ending is LF, whatever machine the file lands on.
- PowerShell scripts were granted CRLF, because they are happier that way. They did not ask for this either.
- The saved ESPN payloads were declared evidence and may never be rewritten. They have taken this as a compliment.
