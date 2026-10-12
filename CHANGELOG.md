# Simulation Log

Release notes for cfbtui, kept the way a fortress overseer keeps a journal. Newest first. Versions follow FibVer.

## 1.1.13 (2026-10-12)

- The repository was given a description, a homepage and ten topic tags, and finally has something to say at parties. The wiki, which nobody had opened, was boarded up.
- The package metadata learned its own address, its issue tracker and a handful of keywords.

## 1.1.8 (2026-10-12)

- The changelog was caught labelling a page 1.1.4, a number that does not exist in this world. Fibonacci counts 3, 5, 8. The page was renumbered 1.1.5 and has stopped insisting.

## 1.1.5 (2026-10-12)

- The README was reorganized into the order a stranger reads it: what it is, what it does, how to get it, how to use it, what to do when it breaks. A table of contents was posted at the door.
- A Troubleshooting corner was built. It currently houses the empty-box icons, the ESPN outage and the board that is empty for a good reason.
- The screenshots were moved next to the words they illustrate, and stopped queueing up in a row.

## 1.1.3 (2026-10-12)

- The README was asked what the program actually does, and until now had never answered in one place. It now has a list. The list is short and none of it is a boast.
- The key table has been given its own heading, so it can be found by someone in a hurry.

## 1.1.2 (2026-10-12)

- The README gained a section for the one-line list and another for the conference picker. Both were photographed looking their best.
- The changelog was found to be missing a page for 1.1.1. The page has been written. It is short.

## 1.1.1 (2026-10-12)

- The photographer was told that Monday is a poor day to photograph football, and was sent to last week's finished games instead. It took the pictures and came back pleased. Every card says Final.
- The photographer now accepts a `--week`, and has learned to photograph the list and the picker.

## 1.1.0 (2026-10-12)

- The games have been offered a second way to sit: a tidy single-file line, one game each, like clerks at a counter. Pressing `v` switches. They have opinions about it.
- A filter was installed on the front door. It admits everyone, then only the Top 25, then only the live, then only the favorites. The rest wait outside and are told "No games match this view".
- A conference picker appeared. Someone chose the SEC. The Big Ten took this personally and was added to the list.
- Favorites now have their own heading and a seat at the front. The other games have been given a heading too, to avoid hurt feelings.
- Two new weeks were discovered past the end of the calendar: Bowls and the Playoff. They had always been there. Nobody had looked.
- The College Football Playoff committee published its first ranking. The AP and Coaches polls were thanked for their service and shown out. The CFP ranking remembers it was invited for the rest of the run.
- A messenger now walks to GitHub at startup to ask whether a newer cfbtui exists. It carries no personal belongings. It may be told to stay home with `--no-update-check`.
- A signing desk was set up for the exe. It is currently unstaffed, as no certificate has been hired, and it says so quietly rather than pretending.
- A rumor that December week 15 was a bowl game was traced to a missing season type and corrected. Regular weeks now say they are regular.
- A first poll that failed on a Saturday used to wait five minutes before trying again. It now waits a few seconds and tries to look less embarrassed.
- Poll intervals set to 0.05 seconds, or to infinity, were noticed by the settings file and gently clamped.
- The update messenger, when handed a bad proxy, now returns empty-handed instead of falling over in the lobby.
- A long Discord board that is copied in parts now says when the last part has been handed over.
- An error message containing square brackets used to be read as instructions. It is now read as a message.
- The empty message banner stopped taking up three rows of floor space while saying nothing.
- Switching from FBS to FCS no longer carries a conference across the border without papers.
- The detail room learned the date of a game, so "Sat 12:00 PM ET" is no longer a mystery about which Saturday.
- A hidden `--selftest` was added so the built exe can prove it starts without anyone watching.
- A linter and a dead-code hunter went through the whole building with clipboards. Unused things were escorted out.
- The README was rewritten for the people who just want to watch football.

## 1.0.0 (2026-10-12)

- The scoreboard has been packed into a single suitcase called `cfbtui.exe`. It carries its own Python, its own stylesheet and its own timezone database, and it asked nobody for anything on arrival. It was opened in an empty folder and was fine.
- The suitcase was weighed, and its fingerprint was written on a slip beside it. Anyone may compare the two. Nobody has yet. The slip waits patiently.
- A version stamp was sewn into the suitcase's lining, so that Windows can say "1.0.0" when asked, and the program says the same thing, and they agree.
- The first run against ESPN from the suitcase went well. Cards appeared in team colors. The ticker ticked. A Nerd Font glyph was spotted in the wild and did not turn into a box.
- A photographer was hired to render the real app to pictures: the grid in three glyph sets, a game's detail room, and the polls. It photographs whatever ESPN is showing at the time, which on a Monday means a great deal of waiting. It will be sent back out on a Saturday.
- The README was rewritten by someone who had actually seen the program. The phrase "planned keys" was retired with honors. Every key in the table now works.
- A release machine was set up on GitHub to answer the ringing of any `v` tag. It runs the tests, checks that the tag and the program agree on their number, builds the suitcase, confirms it can say its own version, and posts it publicly with this log attached. It will not ring until Bill rings it.
- A checklist for a fresh machine was written down, for a day when someone sits at a computer that has never heard of Python. It includes the line "disconnect the network and watch it recover", because it would be rude not to.
- The glyph set was asked about, and the answer was `nerd` for everyone. A person on a fresh machine without the font will see boxes, and the README now says so, and says how to make them go away.
- The program has declared itself 1.0.0, the first number it can tell strangers. Major versions from here on mean that somebody's config file stopped working.

## 0.13.0 (2026-10-12)

- A card was found that could be pressed. Pressing `Enter` on it opens a second room, where the game's scoring plays are laid out in order, each with its clock, its team and the score at that moment. `Esc` leads back to the grid. Nobody was lost.
- A small errand-runner was hired to carry the summary from ESPN every twenty seconds while the game lives. When the game ends, it is thanked and sent home. When the room closes, it is sent home early. Both departures were confirmed by counting.
- A bar of blocks was drawn to show who is likely to win. It fills from the home side and says the percentage twice, in case anyone doubted it. When ESPN has no opinion, the bar stays in its box and says nothing.
- The detail room failed to reach ESPN and said so, in yellow, without leaving. It tried again, succeeded, and took the warning down itself.
- `R` opens the polls: the AP on the left and the Coaches on the right, with the date each was published. On the FCS board it shows the FCS Coaches poll instead, after a reviewer noticed it was showing the wrong division's rankings. A poll that has not been released yet gets a polite shrug.
- While a room is open, the grid's keys fall asleep. A week cannot turn underneath a detail screen. A `q` pressed in either room still quits, because a reviewer reminded us that is what `q` is for.
- `c` copies the focused game as a line of Markdown, with the winner in bold. `C` copies every visible game as a code block with the columns lined up. Both use the unicode glyph set, because Discord has never heard of a Nerd Font.
- A board too long for Discord was cut between games into messages of at most two thousand characters. The clipboard holds only one at a time, so `C` hands over the next part each press. It once started over every time a clock ticked, and was corrected.
- A kickoff two weeks away was copied without its date and could have been mistaken for this Saturday. It now carries the date the card does.
- A game copied with a fence inside its name could have escaped its code block. Its fence was replaced with apostrophes, which nobody will miss.
- A machine with no clipboard was found. The app said so and kept running.
- The games whose diffs had been quietly failing were finally counted in the status bar. There are none today. It was nice to ask.
- Thirty-five tests were added. One of them asserted almost nothing and was told to try harder.

## 0.8.0 (2026-10-12)

- A config file was offered a home under the user's config directory. It declined to exist until someone starred a team, and was praised for its restraint.
- The Config learned to be wrong about nothing. A missing file became the defaults. A corrupt one became the defaults and a warning. A poll interval written as the word "fast" was dropped, and its neighbours were left unharmed.
- Unknown keys from a future version were found at the door. They were ignored without comment and told to come back when they had grown up.
- Command-line flags were hired to override the file for one run only. `--no-config` was given the harder job of pretending the file does not exist.
- A flag-wearing run once tried to write its disguise into the config file when a favorite was starred. It was caught at the door by review, and the file now keeps only what the file said.
- `[` and `]` were taught to turn the page, `t` to come home, and `f` to cross between FBS and FCS. At week 1 and week 15 the pages stop, and a toast says so politely.
- A poll in flight for last week was found arriving after the user had moved on. The scheduler dropped it. A message already queued for the old week was dropped too, by its generation number. Neither complained.
- The ticker was cleared on every switch, as requested. The first board of a new week announces nothing, because forty kickoffs at once was found to be rude.
- The cards became focusable. Arrow keys walk them, clamp at the edges, and land on the final card when a short last row is all that remains below.
- Favorites were given the top of the grid. Press `1` or `2` on a focused card to star its away or home team; a star appears on the card and the ticker highlights their events in reverse video. A game involving two favorites feels very seen.
- A team's star survives a restart. A star that cannot be saved survives the evening and says why it will not survive the night.
- A pregame card more than five days from kickoff now shows its date. A game next week no longer pretends to be this Saturday.
- The period names and status prettifier, found living in two houses, were moved into one.
- A single game that could not be diffed was found hoarding the other games' events. It is now set aside with its old snapshot and tried again next poll.
- The poll started dropping messages into a screen that had already been torn down. The messages were told to stop.
- Three hundred thirty-one tests. The Saturday payload remains unsaved, because it was Monday.

## 0.5.3 (2026-10-12)

- Seven new poets moved into the commit hall: a senryu, a cinquain, a shadorma, an etheree, a limerick, a couplet and a clerihew. The etheree arrived at one syllable and has been growing since.
- A rhyme inspector was given the limerick, the couplet and the clerihew. It checks that the endings agree and, if they do not, sighs once.
- The inspector was told that "seen" and "been" do not rhyme in the dictionary it reads. It has accepted this and so, reluctantly, have the rest of us.

## 0.5.2 (2026-10-12)

- The villanelle was retired. Nobody could prove its refrains were being kept, and several were found wandering off mid-sentence.
- A syllable counter was hired from the CMU Pronouncing Dictionary. It counted the project's own example haiku and announced, flatly, that it was four, seven and six. The haiku has been sent back to school.
- A watcher now notices when a poem ends on "the" or "of". It says nothing cruel, only "did you mean to stop there?"
- Both of them are only warnings. The commit still goes through, though it does so a little embarrassed.

## 0.5.1 (2026-10-12)

- A clerk was hired to stand at the gate on Windows. Each push, it runs the tests and asks the program its version. It does not accept excuses.
- A bot was given a weekly beat. It knocks on the dependencies' doors and reports who has moved on.
- The workflows were sworn in. Nobody has yet seen them fail, which they find suspicious.

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
