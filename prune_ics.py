#!/usr/bin/env python3

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def unfold_lines(lines):
    """Unfold RFC 5545 folded lines."""
    result = []
    for line in lines:
        line = line.rstrip("\r\n")
        if line.startswith((" ", "\t")) and result:
            result[-1] += line[1:]
        else:
            result.append(line)
    return result


def split_property(line):
    """Split an iCalendar property into name/parameters and value."""
    if ":" not in line:
        return line, ""
    return line.split(":", 1)


def property_name(name_with_params):
    return name_with_params.split(";", 1)[0].upper()


def parse_categories(value):
    categories = []
    current = []
    escaped = False

    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ",":
            category = "".join(current).strip()
            if category:
                categories.append(category)
            current = []
        else:
            current.append(char)

    if escaped:
        current.append("\\")

    category = "".join(current).strip()
    if category:
        categories.append(category)

    return categories


def normalize_category(value):
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def category_matches(categories, wanted):
    wanted_normalized = normalize_category(wanted)
    if not wanted_normalized:
        return False
    return any(
        wanted_normalized in normalize_category(category)
        for category in categories
    )


def parse_ical_datetime(name, value):
    params = {}

    if ";" in name:
        for part in name.split(";")[1:]:
            if "=" in part:
                key, val = part.split("=", 1)
                params[key.upper()] = val

    if params.get("VALUE", "").upper() == "DATE":
        try:
            return datetime.strptime(value, "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None

    if value.endswith("Z"):
        try:
            return datetime.strptime(
                value[:-1], "%Y%m%dT%H%M%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    try:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
    except ValueError:
        return None

    tzid = params.get("TZID")
    if tzid:
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid))
        except Exception:
            pass

    return dt.replace(tzinfo=timezone.utc)


def get_event_info(logical_lines):
    dtstart = None
    has_rrule = False
    has_recurrence_id = False
    categories = []

    for line in logical_lines:
        name, value = split_property(line)
        prop = property_name(name)

        if prop == "DTSTART" and dtstart is None:
            dtstart = parse_ical_datetime(name, value)
        elif prop == "RRULE":
            has_rrule = True
        elif prop == "RECURRENCE-ID":
            has_recurrence_id = True
        elif prop == "CATEGORIES":
            categories.extend(parse_categories(value))

    return {
        "dtstart": dtstart,
        "has_rrule": has_rrule,
        "has_recurrence_id": has_recurrence_id,
        "categories": categories,
    }


def clean_html(html, skip_img=False, replace_tags=None, clean_html_mode=False):
    """Clean HTML from an X-ALT-DESC;FMTTYPE=text/html property."""
    if skip_img:
        # Remove a simple image wrapper together with the image, then any
        # remaining standalone img elements.
        html = re.sub(
            r"<div\b[^>]*>\s*<img\b[^>]*>\s*</div>",
            "",
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(r"<img\b[^>]*>", "", html, flags=re.IGNORECASE)

    # Tag replacements deliberately happen before generic cleanup so that,
    # for example, <p></p> becomes <div></div> and can then be preserved.
    for old_tag, new_tag in (replace_tags or []):
        html = re.sub(
            rf"<\s*{re.escape(old_tag)}(\s[^>]*)?>",
            lambda m: f"<{new_tag}{m.group(1) or ''}>",
            html, flags=re.IGNORECASE,
        )
        html = re.sub(
            rf"<\s*/\s*{re.escape(old_tag)}\s*>",
            f"</{new_tag}>",
            html, flags=re.IGNORECASE,
        )

    if clean_html_mode:
        # AI1EC emits literal backslash-n sequences in its HTML. Remove both
        # the two-backslash form (\\n) and the one-backslash form (\n).
        html = html.replace("\\\\n", "")
        html = html.replace("\\n", "")

        # X-ALT-DESC contains a complete HTML document, but calendar clients
        # generally only need the actual content.
        html = re.sub(r"<!DOCTYPE\b[^>]*>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"<head\b[^>]*>.*?</head\s*>", "", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<html\b[^>]*>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"</html\s*>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"<body\b[^>]*>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"</body\s*>", "", html, flags=re.IGNORECASE)

        # Remove empty elements except div. br/hr are intentionally retained.
        empty_tags = (
            "title", "meta", "link", "style", "script", "span",
            "strong", "b", "em", "i", "u", "p", "h1", "h2", "h3",
            "h4", "h5", "h6", "li", "ul", "ol", "table", "tr",
            "td", "th", "section", "article", "header", "footer",
        )
        tag_pattern = "|".join(re.escape(tag) for tag in empty_tags)
        empty_element = re.compile(
            rf"<(?P<tag>{tag_pattern})\b[^>]*>\s*</(?P=tag)\s*>",
            flags=re.IGNORECASE,
        )
        previous = None
        while previous != html:
            previous = html
            html = empty_element.sub("", html)

        html = html.strip()

    return html


def transform_event_html(lines, skip_img=False, replace_tags=None, clean_html_mode=False):
    """Apply HTML transformations to X-ALT-DESC without changing its property type."""
    result = []
    for line in lines:
        name, value = split_property(line)
        if property_name(name) == "X-ALT-DESC":
            params = {}
            if ";" in name:
                for part in name.split(";")[1:]:
                    if "=" in part:
                        key, val = part.split("=", 1)
                        params[key.upper()] = val.strip('"').lower()
            if params.get("FMTTYPE") == "text/html":
                value = clean_html(
                    value,
                    skip_img=skip_img,
                    replace_tags=replace_tags,
                    clean_html_mode=clean_html_mode,
                )
                line = name + ":" + value
        result.append(line)
    return result


def convert_event_for_google(lines, skip_img=False, replace_tags=None, clean_html_mode=False):
    """Move HTML X-ALT-DESC into DESCRIPTION for Google Calendar."""
    html_description = None

    for line in lines:
        name, value = split_property(line)
        if property_name(name) != "X-ALT-DESC":
            continue

        params = {}
        if ";" in name:
            for part in name.split(";")[1:]:
                if "=" in part:
                    key, val = part.split("=", 1)
                    params[key.upper()] = val.strip('"').lower()

        if params.get("FMTTYPE") == "text/html":
            html_description = clean_html(
                value,
                skip_img=skip_img,
                replace_tags=replace_tags,
                clean_html_mode=clean_html_mode,
            )
            break

    result = []
    marker_present = False
    description_present = False

    for line in lines:
        name, value = split_property(line)
        prop = property_name(name)

        if prop == "X-MOZ-GOOGLE-HTML-DESCRIPTION":
            if not marker_present:
                result.append("X-MOZ-GOOGLE-HTML-DESCRIPTION:true")
                marker_present = True
            continue

        if prop == "X-ALT-DESC":
            continue

        if prop == "DESCRIPTION":
            if not description_present:
                if html_description is not None:
                    result.append("DESCRIPTION:" + html_description)
                else:
                    result.append(line)
                description_present = True
            continue

        result.append(line)

    if not description_present and html_description is not None:
        for i, line in enumerate(result):
            if property_name(split_property(line)[0]) == "END":
                result.insert(i, "DESCRIPTION:" + html_description)
                break

    if not marker_present:
        for i, line in enumerate(result):
            if property_name(split_property(line)[0]) == "END":
                result.insert(i, "X-MOZ-GOOGLE-HTML-DESCRIPTION:true")
                break

    return result


def process_calendar(lines, cutoff, keep_categories, google_mode, skip_img=False, replace_tags=None, clean_html_mode=False):
    logical_lines = unfold_lines(lines)
    output = []

    inside_event = False
    event = []

    stats = {
        "total_events": 0,
        "removed_events": 0,
        "kept_by_age": 0,
        "kept_by_recurrence": 0,
        "kept_by_category": 0,
        "category_counts": {},
    }

    def finish_event(event_lines):
        stats["total_events"] += 1
        info = get_event_info(event_lines)

        for category in info["categories"]:
            stats["category_counts"][category] = (
                stats["category_counts"].get(category, 0) + 1
            )

        keep = False

        if info["has_rrule"] or info["has_recurrence_id"]:
            keep = True
            stats["kept_by_recurrence"] += 1
        elif any(
            category_matches(info["categories"], wanted)
            for wanted in keep_categories
        ):
            keep = True
            stats["kept_by_category"] += 1
        elif info["dtstart"] is None:
            keep = True
        elif info["dtstart"] >= cutoff:
            keep = True
            stats["kept_by_age"] += 1

        if keep:
            if google_mode:
                event_lines = convert_event_for_google(
                    event_lines,
                    skip_img=skip_img,
                    replace_tags=replace_tags,
                    clean_html_mode=clean_html_mode,
                )
            elif skip_img or replace_tags or clean_html_mode:
                event_lines = transform_event_html(
                    event_lines,
                    skip_img=skip_img,
                    replace_tags=replace_tags,
                    clean_html_mode=clean_html_mode,
                )
            output.extend(event_lines)
        else:
            stats["removed_events"] += 1

    for line in logical_lines:
        name, value = split_property(line)
        prop = property_name(name)

        if prop == "BEGIN" and value.upper() == "VEVENT":
            inside_event = True
            event = [line]
            continue

        if inside_event:
            event.append(line)
            if prop == "END" and value.upper() == "VEVENT":
                finish_event(event)
                event = []
                inside_event = False
            continue

        output.append(line)

    if inside_event:
        output.extend(event)

    return output, stats


def fold_line(line, limit=75):
    """Fold a content line at UTF-8 octet boundaries."""
    if len(line.encode("utf-8")) <= limit:
        return [line]

    result = []
    current = bytearray()

    for char in line:
        char_bytes = char.encode("utf-8")
        max_len = limit if not result else limit - 1

        if len(current) + len(char_bytes) > max_len:
            result.append(current.decode("utf-8"))
            current = bytearray(b" ")

        current.extend(char_bytes)

    if current:
        result.append(current.decode("utf-8"))

    return result


def make_output(lines):
    result = []
    for line in lines:
        result.extend(fold_line(line))
    return "\r\n".join(result) + "\r\n"


def main():
    parser = argparse.ArgumentParser(
        description="Remove old non-recurring events from an iCalendar file."
    )

    parser.add_argument("input", help="Input .ics file")
    parser.add_argument(
        "-o", "--output",
        help="Output .ics file (default: INPUT.cleaned.ics)"
    )
    parser.add_argument(
        "--years",
        type=float,
        default=3,
        help="Keep events newer than this many years (default: 3)"
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Alternative to --years"
    )
    parser.add_argument(
        "--keep-category",
        action="append",
        default=[],
        metavar="CATEGORY",
        help="Always keep matching categories; may be repeated"
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List categories and event counts, then exit"
    )
    parser.add_argument(
        "--google",
        action="store_true",
        help="Convert HTML X-ALT-DESC to Google-compatible DESCRIPTION"
    )
    parser.add_argument(
        "--skip-img",
        action="store_true",
        help="Remove <img> elements from HTML X-ALT-DESC descriptions"
    )
    parser.add_argument(
        "--replace-tag",
        action="append",
        default=[],
        metavar="OLD|NEW",
        help="Replace HTML tags in X-ALT-DESC, e.g. --replace-tag p|div; may be repeated"
    )
    parser.add_argument(
        "--clean-html",
        action="store_true",
        help="Clean HTML X-ALT-DESC: remove literal \\n sequences, document wrappers, and empty elements (except div)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing output"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress normal status output"
    )

    args = parser.parse_args()

    replace_tags = []
    for spec in args.replace_tag:
        if "|" not in spec:
            parser.error(f"--replace-tag must use OLD|NEW, got: {spec!r}")
        old_tag, new_tag = (part.strip() for part in spec.split("|", 1))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", old_tag) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", new_tag):
            parser.error(f"Invalid --replace-tag value: {spec!r}")
        replace_tags.append((old_tag, new_tag))
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print("Error: input file is not valid UTF-8.", file=sys.stderr)
        return 1

    lines = text.splitlines()
    now = datetime.now(timezone.utc)

    if args.days is not None:
        cutoff = now - timedelta(days=args.days)
        cutoff_description = f"{args.days} days"
    else:
        cutoff = now - timedelta(days=args.years * 365.25)
        cutoff_description = f"{args.years:g} years"

    processed, stats = process_calendar(
        lines,
        cutoff,
        args.keep_category,
        args.google,
        skip_img=args.skip_img,
        replace_tags=replace_tags,
        clean_html_mode=args.clean_html,
    )

    if args.list_categories:
        print("Categories found:")
        for category, count in sorted(
            stats["category_counts"].items(),
            key=lambda item: (-item[1], item[0].casefold()),
        ):
            print(f"  {count:5d}  {category}")
        print(f"\nEvents: {stats['total_events']}")
        return 0

    if args.dry_run:
        print(f"Input:              {input_path}")
        print(f"Cutoff:             {cutoff.isoformat()}")
        print(f"Age criterion:      {cutoff_description}")
        print(f"Google mode:        {'yes' if args.google else 'no'}")
        print(f"Skip images:        {'yes' if args.skip_img else 'no'}")
        print(f"Clean HTML:         {'yes' if args.clean_html else 'no'}")
        print(f"Tag replacements:   {', '.join(a + '|' + b for a, b in replace_tags) or 'none'}")
        print(f"Events found:       {stats['total_events']}")
        print(f"Removed as too old: {stats['removed_events']}")
        print(f"Kept by age:        {stats['kept_by_age']}")
        print(f"Kept by recurrence: {stats['kept_by_recurrence']}")
        print(f"Kept by category:   {stats['kept_by_category']}")
        return 0

    output_path = (
        Path(args.output)
        if args.output
        else input_path.with_name(input_path.stem + ".cleaned.ics")
    )

    try:
        output_path.write_text(
            make_output(processed),
            encoding="utf-8",
            newline=""
        )
    except OSError as exc:
        print(f"Error writing {output_path}: {exc}", file=sys.stderr)
        return 1

    input_size = input_path.stat().st_size
    output_size = output_path.stat().st_size

    if not args.quiet:
        print(f"Input:              {input_path}")
        print(f"Output:             {output_path}")
        print(f"Cutoff:             {cutoff.isoformat()}")
        print(f"Age criterion:      {cutoff_description}")
        print(f"Google mode:        {'yes' if args.google else 'no'}")
        print(f"Skip images:        {'yes' if args.skip_img else 'no'}")
        print(f"Clean HTML:         {'yes' if args.clean_html else 'no'}")
        print(f"Tag replacements:   {', '.join(a + '|' + b for a, b in replace_tags) or 'none'}")
        print(f"Events found:       {stats['total_events']}")
        print(f"Removed as old:     {stats['removed_events']}")
        print(f"Kept by age:        {stats['kept_by_age']}")
        print(f"Kept by recurrence: {stats['kept_by_recurrence']}")
        print(f"Kept by category:   {stats['kept_by_category']}")
        print(f"Input size:         {input_size:,} bytes")
        print(f"Output size:        {output_size:,} bytes")

        if output_size <= 1_000_000:
            print("Google 1 MB limit:  under 1 MB")
        else:
            print("Google 1 MB limit:  OVER 1 MB")

        if args.keep_category:
            print("Keep categories:")
            for category in args.keep_category:
                print(f"  {category}")

        if stats["category_counts"]:
            print("\nCategories found:")
            for category, count in sorted(
                stats["category_counts"].items(),
                key=lambda item: (-item[1], item[0].casefold()),
            ):
                print(f"  {count:5d}  {category}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

