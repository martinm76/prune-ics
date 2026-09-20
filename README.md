# prune-ics
TL;DR : Python script to remove older events from a large .ics file and/or clean up HTML and linebreaks in HTML mode. Primarily made to keep calendars below 1 MB for Google Calendar import. More details below.

If you're planning on working on HTML mode .ics files from All-In One Event Calendar, remmeber to change no_html=true to no_html=false in the download URL.

# iCalendar Pruner

A small, dependency-free Python script for pruning old events from an
[iCalendar](https://datatracker.ietf.org/doc/html/rfc5545) (`.ics`) file.

The primary use case is reducing the size of calendar feeds so they can be
subscribed to by services with feed-size or fetching limitations. The script
was developed and primarily tested with **All-In-One Event Calendar (AI1EC)
for WordPress**, but it is intended to work with ordinary iCalendar files
more generally.

It can also clean up HTML descriptions and optionally convert HTML
descriptions into a format that Google Calendar can render when subscribing
to an ICS feed.

## Features

- Removes non-recurring events older than a configurable age.
- Keeps recurring events (`RRULE`) regardless of age.
- Keeps recurrence exceptions (`RECURRENCE-ID`).
- Keeps events matching one or more categories.
- Fuzzy category matching, including categories with parameters or additional
  text such as `Koncert/Event`.
- Lists categories and event counts.
- Handles `DTSTART` with `VALUE=DATE`, UTC (`Z`), floating times, and
  `TZID`.
- Cleans HTML in `X-ALT-DESC;FMTTYPE=text/html`.
- Optionally removes `<img>` elements from HTML descriptions.
- Optionally replaces HTML tags, such as `<p>` with `<div>`.
- Optionally removes AI1EC-style literal `\n` sequences, HTML document
  wrappers, and empty HTML elements.
- Can convert HTML `X-ALT-DESC` descriptions into Google Calendar-compatible
  HTML in `DESCRIPTION`.
- Preserves the input file; output is written to a separate file by default.
- Folds output lines according to the iCalendar line-length rules.
- Reports input and output size, including whether the output is below 1 MB.

## Requirements

- Python 3.9 or newer is recommended.
- No third-party Python packages are required.

The script uses the standard-library `zoneinfo` module for time zones.

## Basic usage

By default, events older than three years are removed:

```bash
python3 prune_ics.py calendar.ics
```

This creates:

```text
calendar.cleaned.ics
```

The original file is not modified.

### Change the retention period

Keep events newer than five years:

```bash
python3 prune_ics.py calendar.ics --years 5
```

Or use an exact number of days:

```bash
python3 prune_ics.py calendar.ics --days 1095
```

`--days` takes precedence over `--years` when both are supplied.

### Choose the output file

```bash
python3 prune_ics.py calendar.ics -o calendar-pruned.ics
```

### Dry run

To inspect what would happen without creating an output file:

```bash
python3 prune_ics.py calendar.ics --dry-run
```

## Recurring events

Recurring events are always retained when they contain an `RRULE`.

This is intentional: removing an old recurring event merely because its
original `DTSTART` is old could remove the entire recurrence definition,
including future occurrences.

Events containing `RECURRENCE-ID` are also retained because they represent
exceptions or modifications to recurring events.

## Categories

You can force events in a category to be retained even when they are older
than the normal cutoff:

```bash
python3 prune_ics.py calendar.ics --keep-category Koncert
```

The option can be specified multiple times:

```bash
python3 prune_ics.py calendar.ics \
  --keep-category Koncert \
  --keep-category Generalforsamling
```

Category matching is case-insensitive and deliberately fuzzy. For example,
a request for:

```text
Koncert
```

can match a category such as:

```text
Koncert/Event
```

The script also handles multiple categories in a `CATEGORIES` property.

To see the categories found in a calendar:

```bash
python3 prune_ics.py calendar.ics --list-categories
```

## HTML descriptions

AI1EC can put formatted event descriptions into:

```text
X-ALT-DESC;FMTTYPE=text/html
```

The HTML processing options operate directly on this property, whether or
not `--google` is used.

### Remove images

Remove `<img>` elements from HTML descriptions:

```bash
python3 prune_ics.py calendar.ics --skip-img
```

This is useful when a feed contains the same logo or other image in every
event.

### Replace HTML tags

For example, replace paragraph elements with `div` elements:

```bash
python3 prune_ics.py calendar.ics --replace-tag "p|div"
```

Multiple replacements can be supplied:

```bash
python3 prune_ics.py calendar.ics \
  --replace-tag "p|div" \
  --replace-tag "strong|b"
```

Tag replacements are performed before `--clean-html`, which means an empty
`<p></p>` can become `<div></div>` and be retained as a useful spacing
element.

### Clean AI1EC HTML

```bash
python3 prune_ics.py calendar.ics --clean-html
```

The cleanup currently:

- removes literal `\n` and `\\n` sequences from the HTML;
- removes `DOCTYPE`, `html`, `head`, and `body` wrappers;
- removes a number of empty HTML elements;
- retains empty `<div></div>` elements, which can be useful for spacing;
- retains `<br>` and `<hr>` elements.

The HTML options can be combined:

```bash
python3 prune_ics.py calendar.ics \
  --skip-img \
  --replace-tag "p|div" \
  --clean-html
```

Without `--google`, the transformed HTML remains in
`X-ALT-DESC;FMTTYPE=text/html`. The ordinary `DESCRIPTION` property is not
changed.

## Google Calendar

Google Calendar subscription handling differs from clients such as Outlook.
In particular, Google Calendar may ignore the HTML in `X-ALT-DESC` and instead
use the plain `DESCRIPTION` property.

The `--google` option converts an HTML `X-ALT-DESC` description into a Google
Calendar-compatible HTML `DESCRIPTION` and adds:

```text
X-MOZ-GOOGLE-HTML-DESCRIPTION:true
```

Example:

```bash
python3 prune_ics.py calendar.ics \
  --google \
  --skip-img \
  --replace-tag "p|div" \
  --clean-html
```

The result can then be hosted somewhere accessible to Google Calendar and
used as an ICS subscription.

For a web-hosted feed, Google Calendar can also be given a subscription URL
using its calendar subscription workflow.

### Why `--google` is separate

Without `--google`, the script leaves the normal iCalendar HTML description
property intact:

```text
X-ALT-DESC;FMTTYPE=text/html:...
```

With `--google`, the processed HTML is moved to:

```text
DESCRIPTION:<HTML...>
X-MOZ-GOOGLE-HTML-DESCRIPTION:true
```

This makes it possible to maintain a cleaner, standards-oriented feed for
calendar clients that understand `X-ALT-DESC`, while generating a separate
Google-oriented feed when needed.

## Outlook

Outlook clients can use HTML in `X-ALT-DESC` when subscribing to an ICS feed.
For a web-hosted feed, Outlook subscription/import URLs are commonly
prefixed with:

```text
webcal://
```

For example, if the normal HTTP feed is:

```text
https://example.com/calendar/calendar.cleaned.ics
```

the corresponding webcal address is commonly:

```text
webcal://example.com/calendar/calendar.cleaned.ics
```

The exact subscription/import workflow varies between Outlook versions and
Microsoft 365 environments.

For an Outlook-oriented feed, there is normally no need to use `--google`:

```bash
python3 prune_ics.py calendar.ics \
  --skip-img \
  --replace-tag "p|div" \
  --clean-html
```

This leaves the cleaned HTML in `X-ALT-DESC;FMTTYPE=text/html`.

## Typical workflow for a WordPress calendar feed

A typical workflow with AI1EC might look like this:

1. Export the calendar as an `.ics` file.
2. Run the pruner to remove old one-off events.
3. Keep important categories if required.
4. Clean the HTML description.
5. Optionally remove repeated images.
6. Publish the resulting `.ics` file somewhere accessible to calendar
   clients.
7. Subscribe to the resulting feed from Google Calendar, Outlook, or
   another calendar client.

For example:

```bash
python3 prune_ics.py ai1ec-calendar.ics \
  --years 3 \
  --keep-category Koncert \
  --skip-img \
  --replace-tag "p|div" \
  --clean-html \
  -o calendar.cleaned.ics
```

For a Google-specific feed:

```bash
python3 prune_ics.py ai1ec-calendar.ics \
  --years 3 \
  --keep-category Koncert \
  --google \
  --skip-img \
  --replace-tag "p|div" \
  --clean-html \
  -o calendar.google.ics
```

You can then host the generated files separately if you want one feed for
general iCalendar/Outlook clients and another optimized for Google Calendar.

## Google Calendar size limit

The script reports the output size because some calendar subscription
services impose feed-size limits. Keeping the generated file below 1 MB is
particularly useful when working around Google Calendar subscription
limitations.

Example output includes:

```text
Input size:         1,842,317 bytes
Output size:        742,901 bytes
Google 1 MB limit:  under 1 MB
```

The size check is informational; the script does not impose a 1 MB maximum.

## Command-line reference

Run:

```bash
python3 prune_ics.py --help
```

The main options are:

| Option | Description |
|---|---|
| `INPUT` | Input `.ics` file |
| `-o, --output FILE` | Output filename |
| `--years N` | Retain events newer than N years; default is 3 |
| `--days N` | Retain events newer than N days |
| `--keep-category CATEGORY` | Always retain matching categories; repeatable |
| `--list-categories` | List categories and event counts |
| `--google` | Convert HTML `X-ALT-DESC` to Google-compatible `DESCRIPTION` |
| `--skip-img` | Remove `<img>` elements from HTML descriptions |
| `--replace-tag OLD\|NEW` | Replace an HTML tag; repeatable |
| `--clean-html` | Clean AI1EC-style HTML |
| `--dry-run` | Show statistics without writing output |
| `--quiet` | Suppress normal status output |

## Limitations and compatibility

This script is intentionally lightweight and does not attempt to be a full
iCalendar parser or validator.

It is primarily tested against AI1EC-generated calendars, so unusual
iCalendar constructs from other producers may not receive the same level of
testing.

In particular:

- The HTML cleanup is deliberately aimed at the HTML commonly produced by
  AI1EC.
- The Google-specific `DESCRIPTION` handling is intentionally pragmatic
  rather than a general implementation of every calendar client's HTML
  conventions.
- The script assumes UTF-8 input.
- Time-zone handling depends on the time-zone data available to Python.
- The script does not modify the original input file unless you explicitly
  arrange for the output to overwrite it externally.

That said, the event pruning logic works on standard iCalendar constructs and
should be useful with many ordinary `.ics` files.

## License

To keep things simple, the script is licensed under the MIT license
