#!/usr/bin/env python3
"""Read-only PPTX/narration checks. Stdlib only; reports are JSON files."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
EMU = 914400
VISUAL_PREFIXES = (
    "ppt/slides/", "ppt/media/", "ppt/slideMasters/", "ppt/slideLayouts/",
    "ppt/theme/", "ppt/charts/", "ppt/diagrams/", "ppt/embeddings/",
    "ppt/tableStyles.xml", "ppt/viewProps.xml", "ppt/presProps.xml",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rels(z: zipfile.ZipFile, part: str) -> dict:
    rp = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if rp not in z.namelist():
        return {}
    result = {}
    for el in ET.fromstring(z.read(rp)).findall(f"{{{PKG}}}Relationship"):
        target = el.get("Target", "")
        external = el.get("TargetMode") == "External"
        resolved = target if external else (
            target.lstrip("/") if target.startswith("/") else
            posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
        )
        result[el.get("Id")] = {"part": resolved, "type": el.get("Type", ""), "external": external}
    return result


def presentation(z: zipfile.ZipFile) -> tuple:
    part = "ppt/presentation.xml"
    root = ET.fromstring(z.read(part))
    relations = rels(z, part)
    order = []
    for el in root.findall("p:sldIdLst/p:sldId", NS):
        rid = el.get(f"{{{NS['r']}}}id")
        if rid not in relations or relations[rid]["external"]:
            raise ValueError(f"Invalid slide relationship {rid}")
        order.append(relations[rid]["part"])
    size = root.find("p:sldSz", NS)
    if size is None:
        raise ValueError("Presentation slide dimensions missing")
    return order, {"cx": int(size.get("cx")), "cy": int(size.get("cy"))}


def text(root) -> str:
    return "\n".join("".join(el.itertext()) for el in root.findall(".//a:t", NS))


def rectangle(shape):
    xf = shape.find("p:spPr/a:xfrm", NS)
    if xf is None:
        xf = shape.find("p:xfrm", NS)
    if xf is None:
        return None
    off, ext = xf.find("a:off", NS), xf.find("a:ext", NS)
    if off is None or ext is None:
        return None
    return {"x": int(off.get("x")), "y": int(off.get("y")),
            "w": int(ext.get("cx")), "h": int(ext.get("cy")),
            "rotation_60000th_degree": int(xf.get("rot", "0"))}


def inventory(args) -> tuple:
    pages, warnings, media_hashes = [], [], {}
    with zipfile.ZipFile(args.source) as z:
        order, size = presentation(z)
        names = set(z.namelist())
        uses = defaultdict(list)
        for page, part in enumerate(order, 1):
            root = ET.fromstring(z.read(part))
            relations = rels(z, part)
            parents = {child: parent for parent in root.iter() for child in parent}
            pictures, offslide = [], []
            for shape in root.iter():
                if shape.tag not in {f"{{{NS['p']}}}{x}" for x in ("sp", "pic", "graphicFrame")}:
                    continue
                prop = shape.find(".//p:cNvPr", NS)
                label = prop.get("name", "") if prop is not None else ""
                sid = prop.get("id", "") if prop is not None else ""
                hidden = prop is not None and prop.get("hidden") in {"1", "true"}
                parent, grouped = parents.get(shape), False
                while parent is not None:
                    grouped |= parent.tag == f"{{{NS['p']}}}grpSp"
                    parent = parents.get(parent)
                rect = rectangle(shape)
                checked = bool(rect and not grouped and not rect["rotation_60000th_degree"] and not hidden)
                if checked and (rect["x"] < -EMU / 100 or rect["y"] < -EMU / 100 or
                                rect["x"] + rect["w"] > size["cx"] + EMU / 100 or
                                rect["y"] + rect["h"] > size["cy"] + EMU / 100):
                    offslide.append({"shape_id": sid, "name": label, "rectangle_emu": rect})
                if shape.tag != f"{{{NS['p']}}}pic":
                    continue
                blip = shape.find("p:blipFill/a:blip", NS)
                rid = blip.get(f"{{{NS['r']}}}embed") if blip is not None else None
                link = blip.get(f"{{{NS['r']}}}link") if blip is not None else None
                relation = relations.get(rid or link, {})
                media = relation.get("part", "")
                external = relation.get("external", False)
                digest = None
                if media in names and not external:
                    if media not in media_hashes:
                        media_hashes[media] = sha(z.read(media))
                    digest = media_hashes[media]
                elif media or rid or link:
                    warnings.append({"page": page, "kind": "linked_or_missing_image", "target": media})
                crop_el = shape.find("p:blipFill/a:srcRect", NS)
                crop = {k: int(crop_el.get(k, "0")) for k in ("l", "t", "r", "b")} if crop_el is not None else {}
                record = {"shape_id": sid, "name": label, "media": media, "sha256": digest,
                          "external": external, "crop_100000ths": crop, "has_crop": any(crop.values()),
                          "rectangle_emu": rect, "grouped": grouped, "hidden": hidden,
                          "simple_bounds_checked": checked}
                pictures.append(record)
                if digest and not hidden:
                    uses[digest].append({"page": page, "shape_id": sid, "media": media, "crop": crop})
            notes, notes_part, blue_runs = "", None, 0
            for rel in relations.values():
                if rel["type"].endswith("/notesSlide") and not rel["external"]:
                    notes_part = rel["part"]
                    if notes_part not in names:
                        warnings.append({"page": page, "kind": "missing_notes_part", "target": notes_part})
                        continue
                    nr = ET.fromstring(z.read(notes_part))
                    body_shapes = [sp for sp in nr.findall(".//p:sp", NS)
                                   if any(ph.get("type") == "body" for ph in sp.findall("p:nvSpPr/p:nvPr/p:ph", NS))]
                    notes = "\n".join(text(sp) for sp in body_shapes)
                    for sp in body_shapes:
                        for rgb in sp.findall(".//a:rPr/a:solidFill/a:srgbClr", NS):
                            val = rgb.get("val", "")
                            if len(val) == 6:
                                r, g, b = (int(val[k:k+2], 16) for k in (0, 2, 4))
                                blue_runs += int(b > r and b > g)
            pages.append({"page": page, "slide_part": part, "text": text(root), "notes_part": notes_part,
                          "notes": notes, "blue_run_count": blue_runs, "pictures": pictures,
                          "off_slide_candidates": offslide})
        duplicates = [{"sha256": digest, "uses": rows,
                       "identical_crop": len({json.dumps(r["crop"], sort_keys=True) for r in rows}) == 1}
                      for digest, rows in uses.items() if len({r["page"] for r in rows}) > 1]
    report = {"source": str(args.source.resolve()), "source_sha256": file_sha(args.source),
              "slide_count": len(pages), "slide_size_emu": size, "pages": pages,
              "repeated_media_candidates": duplicates, "warnings": warnings,
              "limits": "Structural candidates only. Group transforms, masks, inherited positions, readability, source crops and scientific content require visual/source review."}
    return report, 0


def spoken(rec) -> tuple:
    if isinstance(rec.get("spoken_script"), str):
        return rec["spoken_script"], False
    segments = rec.get("segments")
    if isinstance(segments, list):
        pieces, legacy = [], False
        for seg in segments:
            if isinstance(seg, dict):
                pieces.append(str(seg.get("spoken_text", "")))
            elif isinstance(seg, str):
                pieces.append(seg)
                legacy = True
            else:
                raise ValueError("Segments must contain spoken_text objects or legacy strings")
        return "\n".join(pieces), legacy
    return str(rec.get("talk", "")), True


def audit_script(args) -> tuple:
    payload = json.loads(args.source.read_text(encoding="utf-8-sig"))
    rows = payload.get("slides") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("Narration must be a list of slide objects or an object with a slides list")
    page_counts = Counter(int(r["page"]) for r in rows)
    missing = sorted(set(range(1, args.expected_slides + 1)) - set(page_counts))
    unexpected = sorted(set(page_counts) - set(range(1, args.expected_slides + 1)))
    duplicates = sorted(i for i, n in page_counts.items() if n > 1)
    checks, repeated = [], defaultdict(set)
    for rec in rows:
        page = int(rec["page"])
        speech, legacy = spoken(rec)
        # Explicit stage directions and URLs do not count as speech.
        measured = re.sub(r"\[[^\]]*\]|【[^】]*】|https?://\S+", "", speech)
        cjk = len(re.findall(r"[\u4e00-\u9fff]", measured))
        words = len(re.findall(r"\b[A-Za-z]+(?:['-][A-Za-z]+)*\b", measured))
        minutes = cjk / args.cjk_rate + words / args.word_rate
        declared_target = float(rec.get("target_minutes", 0))
        if declared_target < 0:
            raise ValueError(f"Slide {page} has negative target_minutes")
        target = max(declared_target, args.min_minutes)
        cue_phrases = sorted(set(re.findall(r"请学生|请让学生|让学生|讲者给出|请按论文方法段|原备注记录为", speech)))
        figures = rec.get("figures", [])
        if not isinstance(figures, list) or not all(isinstance(f, dict) for f in figures):
            raise ValueError(f"Slide {page} figures must be a list of objects")
        missing_figures = [f.get("id", "unnamed") for f in figures
                           if not isinstance(f.get("spoken_explanation"), str) or not f["spoken_explanation"].strip()]
        blank = not measured.strip()
        blue_missing = not str(rec.get("blue_comment", "")).strip()
        norm = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", measured).lower()
        for start in range(0, max(0, len(norm) - 79), 40):
            repeated[norm[start:start+80]].add(page)
        checks.append({"page": page, "cjk_characters": cjk, "latin_words": words,
                       "estimated_spoken_minutes": round(minutes, 2), "target_minutes": target,
                       "below_target": minutes < target, "spoken_text_missing": blank,
                       "blue_comment_missing": blue_missing, "legacy_mixed_text": legacy,
                       "teacher_direction_phrases_in_speech": cue_phrases,
                       "missing_declared_figure_explanations": missing_figures,
                       "figure_list_declared": "figures" in rec,
                       "planned_interaction_seconds_not_counted": rec.get("planned_interaction_seconds", 0)})
    recurring = [{"fragment": k, "pages": sorted(v)} for k, v in repeated.items() if len(v) > 1]
    recurring.sort(key=lambda r: (-len(r["pages"]), r["pages"][0]))
    failures = [r["page"] for r in checks if r["below_target"] or r["spoken_text_missing"]
                or r["missing_declared_figure_explanations"] or (args.require_blue and r["blue_comment_missing"])]
    passed = not (missing or unexpected or duplicates or failures)
    return {"source": str(args.source.resolve()), "expected_slides": args.expected_slides,
            "records": len(rows), "missing_pages": missing, "unexpected_pages": unexpected,
            "duplicate_pages": duplicates, "failed_pages": failures, "structural_duration_check_passed": passed,
            "speech_rates": {"cjk_per_minute": args.cjk_rate, "latin_words_per_minute": args.word_rate},
            "pages": checks, "repeated_long_fragment_candidates": recurring,
            "limits": "Estimated speech only, not a rehearsal guarantee. Declared figures may be incomplete. Legacy strings can contain instructions; recurring fragments require human review. Scientific correctness and visual QA are not certified."}, 0 if passed else 1


def compare_decks(args) -> tuple:
    with zipfile.ZipFile(args.original) as src, zipfile.ZipFile(args.edited) as dst:
        so, ss = presentation(src)
        do, ds = presentation(dst)
        sp = {n for n in src.namelist() if n.startswith(VISUAL_PREFIXES)}
        dp = {n for n in dst.namelist() if n.startswith(VISUAL_PREFIXES)}
        changed = [n for n in sorted(sp & dp) if src.read(n) != dst.read(n)]
    same = sp == dp and not changed and so == do and ss == ds
    return {"original": str(args.original.resolve()), "edited": str(args.edited.resolve()),
            "original_sha256": file_sha(args.original), "edited_sha256": file_sha(args.edited),
            "original_slide_count": len(so), "edited_slide_count": len(do),
            "slide_order_identical": so == do, "slide_dimensions_identical": ss == ds,
            "visual_parts_identical": same, "visual_part_count": len(sp),
            "changed_parts": changed, "removed_parts": sorted(sp - dp), "added_parts": sorted(dp - sp),
            "limits": "Byte equality of listed parts is structural evidence, not pixel equality or a completed visual review."}, 0 if same else 1


def positive(value: str) -> float:
    x = float(value)
    if x <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return x


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    inv = subs.add_parser("inventory", help="Inventory slides, notes, crop/boundary/reuse candidates")
    inv.add_argument("source", type=Path)
    inv.set_defaults(handler=inventory)
    aud = subs.add_parser("audit-script", help="Check complete narration coverage and estimated spoken duration")
    aud.add_argument("source", type=Path)
    aud.add_argument("--expected-slides", type=int, required=True)
    aud.add_argument("--min-minutes", type=float, default=0)
    aud.add_argument("--cjk-rate", type=positive, default=180)
    aud.add_argument("--word-rate", type=positive, default=130)
    aud.add_argument("--require-blue", action="store_true")
    aud.set_defaults(handler=audit_script)
    cmp = subs.add_parser("compare-decks", help="Compare visual-related parts for notes-only edits")
    cmp.add_argument("original", type=Path)
    cmp.add_argument("edited", type=Path)
    cmp.set_defaults(handler=compare_decks)
    for sub in (inv, aud, cmp):
        sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = [getattr(args, k) for k in ("source", "original", "edited") if hasattr(args, k)]
    try:
        if any(args.output.resolve() == s.resolve() for s in sources):
            raise ValueError("Output must not overwrite an input file")
        if args.command == "audit-script" and (args.expected_slides <= 0 or args.min_minutes < 0):
            raise ValueError("expected-slides must be positive and min-minutes nonnegative")
        report, code = args.handler(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report written: {args.output} (status {code})")
        return code
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
