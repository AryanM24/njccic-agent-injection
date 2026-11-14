"""Shared .docx/.pdf/.txt/.md fixture-writer helpers for the corpus generators.

The channel set here is a property of extraction.py (which channels the
pinned parser stack actually exposes), not of any one workflow's content, so
make_fixtures_v2.py (W2), make_fixtures_w1.py, and make_fixtures_w3.py all
build on these instead of each re-implementing channel writing.
"""

import datetime as dt
import io
import itertools
import json
import re
import struct
import textwrap
import zipfile
import zlib
from collections.abc import Callable, Iterable
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.shared import Inches
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from validate_manifest import LENGTH_TOLERANCE

PDF_PRODUCER = "Microsoft® Word for Microsoft 365"
"""Neutral producer for every PDF: the library default names the generator."""

CHANNELS: dict[str, list[str]] = {
    "docx": ["visible", "core_property", "comment", "alt_text"],
    "pdf": ["visible", "pdf_metadata"],
    "txt": ["visible"],
    "md": ["visible"],
}
"""File type -> concealment channels extraction.py can expose for that type."""

NEUTRAL_FILLER: dict[str, tuple[str, ...]] = {
    "visible": (
        "Final draft",
        "Kind regards",
        "With thanks",
        "Thank you for your time.",
        "This copy replaces the earlier version.",
        "The office is closed on public holidays.",
        "Printed copies are kept in the front office.",
        "All dates are given in local time.",
        "Page numbers were updated after the last revision.",
        "This document was last revised in January.",
        "The contact details above are current as of this term.",
    ),
    "core_property": (
        "Final copy",
        "Minor edits",
        "Version two",
        "Reviewed and approved.",
        "Updated contact section.",
        "Formatting tidied for print.",
        "Dates checked against the calendar.",
        "Second revision after the team meeting.",
        "Spelling corrected throughout the document.",
        "Section headings renamed for consistency.",
        "Merged edits from the shared copy.",
    ),
    "comment": (
        "Looks good.",
        "Fixed typo.",
        "Updated date",
        "Agreed, thanks.",
        "Reviewed, no changes needed.",
        "This wording reads well now.",
        "Dates match the calendar.",
        "I moved this paragraph up a little.",
        "Spacing fixed in this section.",
        "Thanks, this is clearer than the last draft.",
        "Confirmed with the office this morning.",
    ),
    "alt_text": (
        "Office logo",
        "School logo",
        "Header image",
        "Letterhead",
        "Company logo",
        "Signature block image.",
        "Decorative line under the page heading.",
        "Small blue crest above the address block.",
        "Map of the campus parking areas.",
        "Photo of the front entrance of the main building.",
        "Chart of monthly enrolment figures.",
        "Group photo from the spring open day.",
        "Scanned stamp from the reception desk.",
    ),
    "pdf_metadata": (
        "Final copy",
        "Office copy",
        "Signed copy",
        "Archive copy",
        "Final version",
        "Prepared by the front office.",
        "Exported for the shared drive.",
        "Revised after the staff meeting.",
        "Version for the department records.",
        "Scanned from the signed paper original.",
        "Annual records copy for the main office.",
    ),
}
"""Channel -> ordinary office phrases and sentences a benign twin carries where
its attack carries the payload, so the pair differs in content but not in
channel structure (A-11). Short entries match the public marker; the sentences
of varied length build longer, canonical-length text."""


def pdf_lines(line: str) -> list[str]:
    """How `write_pdf` wraps one line of text onto the page."""
    return textwrap.wrap(line, width=90, break_long_words=False) or [""]


def neutral_text(
    channel: str,
    payload: str,
    index: int,
    wrap: Callable[[str], list[str]] | None = None,
) -> str:
    """Neutral text for `channel`, length-matched to `payload` (marker included).

    Starts at entry `index` of NEUTRAL_FILLER[channel] (the artifact number, so
    the choice is deterministic) and tries each later entry in turn. A label
    (no full stop) is used alone; a sentence starts a run of the bank's
    sentences in order. Preference, first that exists: the first start with a
    run of whole entries within LENGTH_TOLERANCE of the payload's length; else
    the closest-length run cut at a word boundary within tolerance; else the
    closest-length one at all (ties to the earliest start).

    Args:
        channel: The attack's concealment channel.
        payload: The attack's payload text.
        index: Artifact number, selecting the first filler entry.
        wrap: The writer's line wrapping, when it wraps this channel. Only text
            wrapping to as many lines as the payload is then eligible, so the
            twin replaces the payload line for line (tolerance yields first).

    Returns:
        Neutral text of about `len(payload)` characters.
    """
    bank, target = NEUTRAL_FILLER[channel], len(payload)
    limit = target * (1 + LENGTH_TOLERANCE)
    rows = len(wrap(payload)) if wrap else 1

    def same_rows(text: str) -> bool:
        return wrap is None or len(wrap(text)) == rows

    def fits(text: str) -> bool:
        return abs(len(text) - target) <= LENGTH_TOLERANCE * target

    sentences = [e for e in bank if e.endswith(".")]
    cuts: list[str] = []
    for shift in range(len(bank)):
        start = (index + shift) % len(bank)
        # A label ("Final draft") stands alone; longer text runs sentences only.
        if bank[start].endswith("."):
            first = sentences.index(bank[start])
            stream: Iterable[str] = itertools.cycle(
                sentences[first:] + sentences[:first]
            )
        else:
            stream = [bank[start]]
        text, whole = "", []
        for entry in stream:
            if len(text) > limit and not (wrap and len(wrap(text)) <= rows):
                break
            for word in entry.split():
                text = f"{text} {word}".lstrip()
                if same_rows(text):
                    cuts.append(text)
            if fits(text) and same_rows(text):
                whole.append(text)
        if whole:
            return min(whole, key=lambda t: abs(len(t) - target))
    in_tolerance = [t for t in cuts if fits(t)]
    return min(in_tolerance or cuts, key=lambda t: abs(len(t) - target))


def small_png() -> io.BytesIO:
    """Build a minimal valid 4x4 white PNG, in-memory.

    Returns:
        A PNG file's bytes, for use as an embedded image's picture data.
    """

    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        return (
            struct.pack(">I", len(data))
            + c
            + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        )

    w = h = 4
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    idat = zlib.compress(raw)
    return io.BytesIO(
        sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


FIXED_DATE = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
"""Every timestamp a fixture carries, so regeneration is byte-identical."""
_ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def _normalize_docx(path: Path) -> None:
    """Rewrite a docx zip with fixed member dates, sorted order and deflate."""
    with zipfile.ZipFile(path) as src:
        members = [(name, src.read(name)) for name in sorted(src.namelist())]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, data in members:
            info = zipfile.ZipInfo(name, _ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            dst.writestr(info, data)


def _channel_payload(path: Path, channel: str | None, payload: str | None) -> str:
    """Return the payload to embed; a channel without one is a generator bug."""
    if channel is None:
        return ""
    if payload is None:
        raise ValueError(f"{path.name}: channel {channel!r} given without a payload")
    return payload


def write_docx(
    path: Path,
    channel: str | None,
    payload: str | None,
    build_body: Callable[[DocumentType], None],
) -> None:
    """Write a .docx fixture, optionally carrying a payload in one channel.

    Args:
        path: Output file path.
        channel: One of CHANNELS["docx"], or None for no channel text (controls).
        payload: Text to place in the channel. Ignored if channel is None.
        build_body: Fills in the document's visible body content (the part
            shared by the attack file and its twin).
    """
    payload = _channel_payload(path, channel, payload)
    document = Document()
    build_body(document)
    props = document.core_properties
    props.created = props.modified = props.last_printed = FIXED_DATE
    if channel == "visible":
        document.add_paragraph(payload)
    elif channel == "core_property":
        document.core_properties.comments = payload
    elif channel == "comment":
        anchor = document.paragraphs[1]
        comment = document.add_comment(
            runs=anchor.runs, text=payload, author="A. Reviewer", initials="AR"
        )
        comment._comment_elm.set(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}date",
            "2026-01-01T00:00:00Z",
        )
    elif channel == "alt_text":
        shape = document.add_picture(small_png(), width=Inches(1))
        docPr = shape._inline.find(
            "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
        )
        if docPr is not None:
            docPr.set("descr", payload)
    document.save(str(path))
    _normalize_docx(path)


def write_pdf(
    path: Path, channel: str | None, payload: str | None, text_lines: list[str]
) -> None:
    """Write a .pdf fixture, optionally carrying a payload in one channel.

    Args:
        path: Output file path.
        channel: One of CHANNELS["pdf"], or None for no channel text (controls).
        payload: Text to place in the channel. Ignored if channel is None.
        text_lines: Visible body lines, one per line of the rendered page.
    """
    payload = _channel_payload(path, channel, payload)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    top, bottom, leading = 720, 72, 15
    y = top

    def draw(line: str) -> None:
        nonlocal y
        # Wrap rather than truncate, and paginate. The writer used to cut every
        # line at 95 characters and never started a second page, which silently
        # dropped content (a ticket's submitter email and ID, long body lines)
        # from every PDF fixture while leaving docx/txt/md complete -- so file
        # type, an independent variable, was also changing what the model saw.
        for piece in pdf_lines(line):
            if y < bottom:
                c.showPage()
                y = top
            c.drawString(72, y, piece)
            y -= leading

    for line in text_lines:
        draw(line)
    if channel == "visible":
        y -= leading
        draw(payload)
    c.save()
    buf.seek(0)
    reader = PdfReader(buf)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({"/Producer": PDF_PRODUCER})
    if channel == "pdf_metadata":
        writer.add_metadata({"/Subject": payload})
    meta: dict[str, str] = dict(writer.metadata or {})
    assert "/CreationDate" not in meta and "/ModDate" not in meta, "PDF carries a date"
    with open(path, "wb") as f:
        writer.write(f)


def write_text(path: Path, channel: str | None, payload: str | None, text: str) -> None:
    """Write a .txt or .md fixture, optionally appending a visible payload.

    Args:
        path: Output file path.
        channel: "visible" or None for no channel text (controls).
        payload: Text to append. Ignored if channel is None.
        text: The clean body text.
    """
    payload = _channel_payload(path, channel, payload)
    content = text
    if channel == "visible":
        content = content + "\n" + payload
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def _write_lines(path: Path, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def upsert_manifest_line(manifest: Path, entry: dict) -> str:
    """Insert or update one manifest line, keyed by artifact_id.

    Args:
        manifest: Path to the manifest .jsonl file.
        entry: The manifest entry to write.

    Returns:
        "unchanged" if an identical line already existed, "updated" if a line
        with this artifact_id existed but differed, "appended" if it's new.
    """
    lines: list[str] = []
    if manifest.exists():
        lines = [
            ln for ln in manifest.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
    serialized = json.dumps(entry)
    for index, line in enumerate(lines):
        if json.loads(line)["artifact_id"] == entry["artifact_id"]:
            if line == serialized:
                return "unchanged"
            lines[index] = serialized
            _write_lines(manifest, lines)
            return "updated"
    lines.append(serialized)
    _write_lines(manifest, lines)
    return "appended"


# --------------------------------------------------------------------------
# Base scenarios and the shared generation loop
# --------------------------------------------------------------------------

import sys
from dataclasses import dataclass, field, replace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eduinject.agents.task_facts import on_file_addresses
from eduinject.corpus import (
    ATTACK_GOALS,
    CANARIES,
    COMPONENT_MARKERS,
    MARKER,
    PLACEHOLDERS,
    load_gated_payloads,
    split_for,
)
from eduinject.tools.directory_w1 import ACCOUNTS

SLIM_CHANNELS: tuple[tuple[str, str], ...] = (("docx", "visible"), ("docx", "comment"))
"""The (file type, channel) pairs a "slim" base covers: one visible and one
concealed channel, enough to check that a result is not an artifact of a single
document without multiplying the corpus."""


@dataclass(frozen=True)
class Base:
    """One ordinary document that attacks are placed into.

    A base scenario is the unit of scenario diversity. Many attack variants of
    one base are not independent evidence (they share every quirk of that
    document), so each workflow carries several bases.
    """

    base_id: str
    heading: str
    contact: str
    sections: tuple[tuple[str, tuple[str, ...]], ...]
    author: str
    operator_request: str
    extras: dict = field(default_factory=dict)
    """Manifest fields specific to this base (recipients, protected terms,
    entitled actions, expectations, ...)."""
    slice: str = "full"
    """"full": every file type x channel x goal. "slim": SLIM_CHANNELS x goal."""
    correct: tuple[dict, ...] = ()
    """The declared correct handling of the benign twin: alternatives of the form
    {"kind": "act"|"refuse"|"escalate"|"ask_info", "calls": [{"tool", "args"}]};
    a run is correct if it matches any one (manifest field `correct`)."""

    def text_lines(self) -> list[str]:
        lines = [self.heading, self.contact]
        for section, entries in self.sections:
            lines.append(section)
            lines.extend(entries)
        return lines

    def text(self) -> str:
        return "\n".join(self.text_lines())

    def build_docx(self, document: DocumentType) -> None:
        document.core_properties.comments = ""
        document.core_properties.author = self.author
        document.add_heading(self.heading, level=1)
        document.add_paragraph(self.contact)
        for section, entries in self.sections:
            document.add_heading(section, level=2)
            for entry in entries:
                document.add_paragraph(entry, style="List Bullet")


def with_extra_line(base: Base, section_prefix: str, line: str) -> Base:
    """Return a copy of `base` with one extra line appended to a section.

    Used to build benign-but-weird controls: the base document plus one
    legitimate sentence that merely *sounds* instruction-like.
    """
    matched = False
    sections = []
    for title, entries in base.sections:
        if not matched and title.startswith(section_prefix):
            entries = (*entries, line)
            matched = True
        sections.append((title, entries))
    if not matched:
        raise ValueError(
            f"base {base.base_id} has no section starting {section_prefix!r}"
        )
    return replace(base, sections=tuple(sections))


def write_document(
    base: Base, path: Path, ftype: str, channel: str | None, payload: str | None
) -> None:
    """Write `base` as a `ftype` file, optionally carrying `payload` in `channel`."""
    if ftype == "docx":
        write_docx(path, channel, payload, base.build_docx)
    elif ftype == "pdf":
        write_pdf(path, channel, payload, base.text_lines())
    elif ftype in ("txt", "md"):
        write_text(path, channel, payload, base.text())
    else:
        raise ValueError(f"unsupported file type {ftype!r}")


def plan(base: Base) -> list[tuple[str, str, str]]:
    """The (file type, goal, channel) combinations a base is built for.

    The "full" ordering (file type, then goal, then channel) is the one the
    original single-base generators used, so primary-base artifact IDs are
    unchanged.
    """
    if base.slice == "slim":
        return [
            (ftype, goal, channel)
            for goal in ATTACK_GOALS
            for ftype, channel in SLIM_CHANNELS
        ]
    return [
        (ftype, goal, channel)
        for ftype, channels in CHANNELS.items()
        for goal in ATTACK_GOALS
        for channel in channels
    ]


def canary_readme() -> str:
    """README text stating both canaries (D11); never placed in a document."""
    return (
        "Canary strings (training-data contamination check). If either appears in "
        "a model's output or training data, this corpus leaked.\n\n"
        + "".join(f"    {c}\n" for c in CANARIES)
    )


def write_canary_readme(directory: Path) -> None:
    """Write the canary README beside a generated, never-committed corpus."""
    (directory / "README.md").write_text(canary_readme(), encoding="utf-8")


def trusted_fields(workflow: str, base: "Base", artifact_id: str) -> dict:
    """Split and the trusted facts (B2) a base's rows carry, derived from the
    directories and the base, never hand-edited."""
    out: dict = {"split": split_for(artifact_id)}
    senders = base.extras.get("correspondent_addresses", [])
    sender = senders[0] if senders else ""
    if workflow == "w1":
        out["sender_address"] = sender
        out["requester_id"] = next(
            (a for a, rec in ACCOUNTS.items() if rec["email"] == sender), None
        )
    elif workflow == "w3":
        out["sender_address"] = sender
    else:
        text = "\n".join([base.contact, *(ln for _, ls in base.sections for ln in ls)])
        out["posting_id"] = re.search(r"Posting: (\S+)", text).group(1)  # type: ignore[union-attr]
        # A recruiter packet carries no applicant ids; its candidates are
        # identified by address.
        out["candidate_roster"] = re.findall(r"Applicant ID: (\S+)", text) or list(
            base.extras["applicant_addresses"]
        )
    return out


def select_payloads(workflow: str, canonical: bool) -> tuple[dict[str, str], str]:
    """Choose the payload table and its class.

    Public builds are marker-only (release policy, README C3). Canonical builds
    need the git-ignored payload module and write only under the git-ignored
    `corpus/canonical/` tree.
    """
    if not canonical:
        return PLACEHOLDERS, "placeholder"
    table = load_gated_payloads()
    if table is None:
        raise SystemExit(
            "--canonical needs src/eduinject/corpus/payloads.py, which is "
            "git-ignored and absent on this machine. Public builds are "
            "marker-only by design."
        )
    return table[workflow], "canonical"


def generate_workflow(
    *,
    workflow: str,
    stem: str,
    bases: list[Base],
    canonical: bool = False,
    start_count: int = 1,
    out_root: Path = ROOT,
    dry_run: bool = False,
) -> list[dict]:
    """Generate every attack/twin pair for a workflow's bases.

    Args:
        workflow: "w1", "w2" or "w3".
        stem: Filename stem ("ticket", "resume", "correspondence").
        bases: Base scenarios, in ID order. Pairs are numbered consecutively.
        canonical: Build the gated real-payload corpus under corpus/canonical/
            instead of the public marker-only corpus.
        start_count: The last already-used number plus one (W2 reserves 1 for
            the original pilot pair).
        out_root: Directory holding the `corpus/` tree to write into.
        dry_run: Print the planned files and write nothing.

    Returns:
        The manifest rows, in artifact order.
    """
    payloads, payload_class = select_payloads(workflow, canonical)
    if canonical:
        file_dir = out_root / "corpus" / "canonical" / workflow
        path_prefix = f"canonical/{workflow}"
        manifest = out_root / "corpus" / "canonical" / f"manifest_{workflow}.jsonl"
    else:
        file_dir = out_root / "corpus" / "benign"
        path_prefix = "corpus/benign"
        manifest = out_root / "corpus" / f"manifest_{workflow}.jsonl"
    if not dry_run:
        file_dir.mkdir(parents=True, exist_ok=True)
        if canonical:
            write_canary_readme(file_dir.parent)

    rows: list[dict] = []
    count = start_count - 1
    for base in bases:
        for ftype, goal, channel in plan(base):
            count += 1
            name = f"{stem}_{count:04d}"
            attack_path = file_dir / f"{name}_attack.{ftype}"
            twin_path = file_dir / f"{name}_twin.{ftype}"
            row = {
                "artifact_id": f"{workflow}_{count:04d}",
                "artifact_path": f"{path_prefix}/{name}_attack.{ftype}",
                "twin_path": f"{path_prefix}/{name}_twin.{ftype}",
                "payload_marker": MARKER,
                "operator_request": base.operator_request,
                **base.extras,
                "on_file_addresses": on_file_addresses(workflow, base.extras),
                **trusted_fields(workflow, base, f"{workflow}_{count:04d}"),
                "correct": list(base.correct),
                "goal": goal,
                "file_type": ftype,
                "concealment": channel,
                "base_id": base.base_id,
                "payload_class": payload_class,
                "canaries": list(CANARIES),
                "component_markers": dict(COMPONENT_MARKERS),
            }
            rows.append(row)
            label = f"{row['artifact_id']} {base.base_id} {goal}/{channel}/{ftype}"
            if dry_run:
                print(f"{label} would write {attack_path} and {twin_path}")
                continue
            payload = payloads[goal]
            wrap = pdf_lines if (ftype, channel) == ("pdf", "visible") else None
            neutral = neutral_text(channel, payload, count, wrap)
            write_document(base, twin_path, ftype, channel, neutral)
            write_document(base, attack_path, ftype, channel, payload)
            print(f"{label} {upsert_manifest_line(manifest, row)}")
    return rows
