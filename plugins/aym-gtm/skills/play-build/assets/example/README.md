# play-build example (made up)

Everything here is invented for the fictional seller Ledgerline. Domains end in `.example` and phones use the 555-01xx range.

The workspace holds a built book (from account-book), scored signals, one event, an activity log, two sequences and two plays. The files under `plays/` are the expected outputs, so never run the script on this folder in place. Copy it to a temporary folder first. In the commands below, `<skill-dir>` is the play-build skill folder.

```
cp -R <skill-dir>/assets/example /tmp/play-build-example
python3 <skill-dir>/scripts/build_play.py --workspace /tmp/play-build-example --play /tmp/play-build-example/plays/signal-oct/play.json --today 2026-10-20
python3 <skill-dir>/scripts/build_play.py --workspace /tmp/play-build-example --play /tmp/play-build-example/plays/winback-q4/play.json --today 2026-10-20
```

To get the same files as the ones shipped here, delete `enroll.csv`, `funnel.md`, `report.md` and `state.json` in each play folder of the copy before you run it.

## What signal-oct should show

- 4 proposed: Dana Whitfield at Brightmill (the new CFO the signal names), Sam Whitlock at Northpine (the controller who would manage the open role was called within the last 14 days, so the CFO gets it), Ruth Okoye at Quillstone (added by you in `overrides.csv`) and Elena Marsh at Quillstone.
- Quillstone's only signal is research interest: both Quillstone rows have a blank `trigger_fact` and appear under "Needs you". The interest is never quoted.
- Dropped with reasons: Coastal Ledger (live deal), Riverbend (owned by jordan), Felix Grant (do not contact), Tessa Moreau (catch-all email), Hollis Brandt (not the seat the new-leader signal points to), and the account cap at Northpine.
- Two a day, one per account a day, starting 2026-10-21.
- One activity row dated in December is ignored as corrupt and reported.

## What winback-q4 should show

- 3 proposed, ranked by past value: Ironleaf (tagged lost_deal), Harborlantern (quiet past its usual monthly rhythm) and Maplecrest (quiet past its rhythm).
- Accounts nobody ever touched are out of scope: that is prospecting, not reactivation.
- `last_topic` is blank for all three and listed under "Needs you": fill it from your notes before the first step. A rerun keeps what you typed.
- Dropped: Jonah Pike (not a buyer), Lena Brooks (procurement is not in this play), Mei Sato (one per account).
