# Simulation Log

Release notes for cfbtui, kept the way a fortress overseer keeps a journal. Newest first. Versions follow FibVer.

## 1.3.0 (2026-10-13)

- The scoreboard used to leave the building in one crate, stamped for Windows. The loading dock now packs five: Windows, Linux on x86_64 and on arm64, and macOS on Apple silicon and on Intel. Each is built by its own crew on its own machine, and all of them go out on one release with a single SHA256SUMS manifest nailed to the side instead of a tag on each crate.
- The Linux crates are packed in an older room, Debian 11, so they open on any distribution from 2020 onward rather than only the newest.
- For anyone who keeps their own Python, the same release carries the source tarball and a wheel, so pipx or uv can set it up with no crate at all.
- The inspectors now run their checklists on Linux and macOS as well as Windows before anything is allowed out, and every crate is opened and started once on the dock before it is loaded.
- The front-door notice tells each kind of visitor which file is theirs, where their settings scroll lives, and how to check the manifest.
- The first Linux inspection found a fault the Windows room had hidden by luck of timing: close a live game's detail page at the wrong instant and the runner fetching its scoring plays came back to find the page already torn down, and brought the whole scoreboard down with it. The runner now notices the empty room and leaves quietly.

## 1.2.2 (2026-10-13)

- The name tags handed out in 1.2.1 were checked against ESPN's own roll call, and one was wrong: Conference 179 is the Ohio Valley, not the Big South-OVC. It is now OVC. The Missouri Valley took ESPN's own short name, MVFC, and the last stranger, Conference 32, turned out to be the FCS Independents.

## 1.2.1 (2026-10-13)

- The conference picker listed three strangers at the bottom of the room: Conference 179, Conference 29 and Conference 48. They were FCS conferences ESPN had numbered and the overseer had never been introduced to. They are now Big South-OVC, Southern and CAA, and the rest of the FCS crowd got name tags too: Big Sky, Missouri Valley, MEAC, NEC, Patriot, Southland, SWAC and UAC.

## 1.2.0 (2026-10-12)

- A troupe of inspectors was sent through the scoreboard with clipboards. They pressed every key, fed it broken ledgers, unplugged the network and shouted at it in tiny rooms. About 800 of their checklists were kept in the cellar under tests/uat, and four faults came to light.
- A settings scroll saved by Notepad with its invisible byte-order mark was being thrown away as gibberish. The overseer now reads past the mark and keeps the settings.
- A courier once swore a team had scored a number with thirty zeroes, and the clerk tried to build a table that large to work out how. The clerk now writes "some points, unknown" and moves on.
- When ESPN said "slow down" (429) or "come back later" (408), the errand-runner gave up at once. It now waits and tries again, the way it does for a server error.
- A bowl-week ledger that forgot to say which season it belonged to was filed as Week 1. The overseer now reads the season off the games themselves, and Bowls and the Playoff land where they belong.
- The front-door notice claimed scores arrive every five minutes on quiet days. It now says two.
- Known gap, left for later: if the rankings only arrive after a game has started, the ticker misses that game's "upset watch" line. The cards still change color correctly.

## 1.1.144 (2026-10-12)

- The workshop was swept out. The scaffolding, the hooks and the notes the builders left for each other were carted away, and the scoreboard stands in a clean room.
- The errand-runner who asks ESPN for scores used to decide its pace by whether a game was on. It now looks over its shoulder instead: while anyone has touched the keyboard or mouse in the last five minutes it runs every twenty seconds, games or no games, and once the room has been empty that long it slows to every two minutes. It does not care which window is in front. ESPN has not noticed.
- Someone walking back to the computer is greeted with a fresh poll rather than the tail of a two-minute wait.
- The status bar now says "(away)" beside a slow countdown, so nobody has to ask the overseer what the long number means.
- The posters on the front door were taken down. They were drawings of the scoreboard, and not good ones: the colors had drained out and the letters wandered. The new posters are photographs, taken through a real terminal window, and the team colors are back.
- The package's dependency list was found hiding under the web links, where pip could not see it. It has been returned to the right shelf.

## 1.1.89 (2026-10-12)

- The poster's scoreboard was relieved of its costume. It no longer claims to be PowerShell, Terminal or anything else. It is a dark window with a plain strip on top, and it is just here for the football.

## 1.1.55 (2026-10-12)

- The little dropdown arrow on the poster's tab bar was discovered to be the letter V, wearing a hat. It has been replaced by a real chevron and is much happier.

## 1.1.34 (2026-10-12)

- The poster's scoreboard was found sitting in a window with three little traffic-light dots, which is how Macs dress. It has been moved into a Windows Terminal tab marked "Windows PowerShell" and says it feels more like itself.

## 1.1.21 (2026-10-12)

- A 1280 by 640 poster was made for the repository's front door. It has the name in large letters, a promise in smaller letters, and a scoreboard peeking in from the right, as though it had been listening.

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

## 0.2.0 (2026-10-12)

- Founded a repository in an empty directory on a Sunday afternoon. It had no commits and no opinions.
- Chose Python and Textual. A Go binary was considered and politely declined.
- Painted six team colors on the wall to see whether Windows Terminal could tell them apart. It could.
- Hired a StatusBar. It has learned to tell the time and announce the version. It does nothing else and seems content.
- Fetched four payloads from ESPN and stored them under `tests/fixtures/` as evidence: a pregame week, a finished Saturday, the rankings, and one Texas game in full.
- Wrote twenty tests. All twenty passed. The founders were suspicious and ran them again. They passed again.
- Made the repository public under the MIT license and pushed it to GitHub. The README carries a disclaimer about ESPN that nobody will read.
- The scoreboard has not been built. The games go on without it.

