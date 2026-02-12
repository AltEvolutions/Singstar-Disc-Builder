from __future__ import annotations

import argparse
from pathlib import Path

from .layout import resolve_input
from .inspect import inspect_export
from .plan import make_plan
from .merge import merge_build, MergeOptions, MergeError
from .util import dumps_pretty


def _cmd_gui(_args: argparse.Namespace) -> int:
    """Launch the GUI (auto: Qt if available, else Tkinter)."""
    try:
        from .app_logging import init_app_logging
        init_app_logging(component="gui")
    except Exception:
        pass
    try:
        import PySide6  # type: ignore
    except Exception:
        PySide6 = None  # type: ignore

    # Prefer Qt when available. Only fall back to Tk if Qt is unavailable or fails.
    if PySide6 is not None:
        from .qt_app import run_qt_gui
        try:
            rv = run_qt_gui()
            # If Qt returns None, it usually means we never reached app.exec()/a window.
            try:
                rc = int(rv)
            except Exception:
                rc = None
            if rc is None:
                print(
                    "[gui] Qt returned no exit code (likely exited before showing a window). "
                    "Falling back to Tk. (To reproduce: `python -m spcdb_tool gui-qt`)"
                )
            else:
                # Normal close -> rc=0. Non-zero -> treat as Qt failure and fall back.
                if rc == 0:
                    return 0
                print(
                    f"[gui] Qt exited with rc={rc}. Falling back to Tk. "
                    "(To reproduce: `python -m spcdb_tool gui-qt`)"
                )
        except Exception as e:
            # Qt is present but failed at runtime. Fall back to Tk so the user can keep working,
            # but keep the error visible for debugging.
            print(
                f"[gui] Qt launch failed: {e}. Falling back to Tk. "
                "(To reproduce: `python -m spcdb_tool gui-qt`)"
            )

    from .gui_app import run_gui
    run_gui()
    return 0


def _cmd_gui_tk(_args: argparse.Namespace) -> int:
    """Launch the GUI (Tkinter)."""
    try:
        from .app_logging import init_app_logging
        init_app_logging(component="gui_tk")
    except Exception:
        pass
    from .gui_app import run_gui

    run_gui()
    return 0




def _cmd_gui_qt(_args: argparse.Namespace) -> int:
    """Launch the GUI (PySide6 / Qt)."""
    try:
        from .app_logging import init_app_logging
        init_app_logging(component="gui_qt")
    except Exception:
        pass
    from .qt_app import run_qt_gui

    try:
        rv = run_qt_gui()
        try:
            rc = int(rv)
        except Exception:
            rc = None
        if rc is None:
            # This is the "silent exit" failure mode. Make it loud and non-zero.
            try:
                print("[gui-qt] Qt returned no exit code (likely exited before showing a window).")
            except Exception:
                pass
            return 2
        return rc
    except BaseException as e:
        import logging
        import traceback
        # Make sure *anything* (including SystemExit) can't disappear silently.
        try:
            tb = traceback.format_exc()
        except Exception:
            tb = f"{type(e).__name__}: {e}"
        try:
            logging.getLogger("spcdb_tool").error("[gui-qt] Uncaught error during Qt launch:\n%s", tb)
        except Exception:
            pass
        try:
            print("[gui-qt] Uncaught error during Qt launch (see logs):")
            print(tb)
        except Exception:
            pass
        # Preserve Ctrl+C behavior.
        if isinstance(e, KeyboardInterrupt):
            raise
        return 2


def _cmd_qt_diag(_args: argparse.Namespace) -> int:
    """Diagnose whether Qt/PySide6 can create a QApplication on this machine.

    This is intentionally lightweight and prints to stdout/stderr so the Windows
    launcher can capture plugin/platform errors (e.g., missing DLLs).
    """
    try:
        from .app_logging import init_app_logging
        init_app_logging(component="qt_diag")
    except Exception:
        pass

    print("[qt-diag] starting")
    try:
        import sys
        print(f"[qt-diag] python={sys.version}")
    except Exception:
        pass

    try:
        import PySide6  # type: ignore
        print(f"[qt-diag] PySide6={getattr(PySide6, '__version__', 'unknown')}")
    except Exception as e:
        print(f"[qt-diag] PySide6 import failed: {e}")
        return 2

    # Import Qt modules.
    try:
        print("[qt-diag] importing QtCore/QtWidgets")
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QWidget
        print("[qt-diag] imports OK")
    except Exception as e:
        print(f"[qt-diag] Qt imports failed: {e}")
        return 2

    # Create an application and a tiny widget, then quit immediately.
    try:
        print("[qt-diag] creating QApplication")
        app = QApplication.instance() or QApplication([])
        print("[qt-diag] QApplication created")
        w = QWidget()
        w.setWindowTitle("SingStar Disc Builder Qt diag")
        w.resize(200, 80)
        w.show()
        app.processEvents()
        print(f"[qt-diag] widget visible={bool(w.isVisible())}")

        # Quit quickly; we only care that we can start.
        QTimer.singleShot(200, app.quit)
        rc = int(app.exec())
        print(f"[qt-diag] event loop exited rc={rc}")
        return 0
    except Exception as e:
        print(f"[qt-diag] failed during QApplication/show/exec: {e}")
        return 2


def _cmd_support_bundle(args: argparse.Namespace) -> int:
    """Export a privacy-safe support bundle zip (logs/settings/system summary)."""
    from datetime import datetime
    from .controller import export_support_bundle

    out = str(getattr(args, "out", "") or "").strip()
    if not out:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = f"spcdb_support_{ts}.zip"

    res = export_support_bundle(
        output_path=Path(out),
        disc_states=None,
        redact_paths=(not bool(getattr(args, "no_redact", False))),
    )
    if bool(getattr(args, "json", False)):
        print(dumps_pretty(res))
    else:
        print(f"Support bundle written: {res.get('bundle_path')}")
        try:
            print(f"Size: {float(res.get('size_mb') or 0.0):.2f} MB")
        except Exception:
            pass
        try:
            inc = res.get("included") or []
            if inc:
                print("Includes: " + ", ".join(str(x) for x in inc))
        except Exception:
            pass
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    ri = resolve_input(args.path)

    # keep temp dir alive until after output
    report = inspect_export(
        export_root=ri.export_root,
        kind=ri.kind if ri.kind != "zip_extracted" else "export_folder",
        input_path=str(ri.original),
        warnings=list(ri.warnings),
    )

    if args.json:
        print(dumps_pretty(report))
    else:
        _print_human(report)

    if ri.temp_dir is not None:
        ri.temp_dir.cleanup()
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate a disc/export folder and report issues.

    Exit codes:
      - 0: OK
      - 1: WARN (non-blocking issues)
      - 2: FAIL (blocking errors)
    """
    from .controller import validate_one_disc

    rep = validate_one_disc("disc", str(args.path))
    if bool(getattr(args, "json", False)):
        print(dumps_pretty(rep))
    else:
        _print_validate_human(rep)

    sev = str(rep.get("severity") or "").upper()
    if sev == "OK":
        return 0
    if sev == "WARN":
        return 1
    return 2


def _print_human(r) -> None:
    print("== SingStar Disc Builder: INSPECT ==")
    print(f"Input:        {r.input_path}")
    print(f"Export root:  {r.export_root}")
    if r.product_code or r.product_desc:
        print(f"Product:      {r.product_desc or ''} (code {r.product_code or '?'})")
    print(f"Banks:        {r.versions_in_config} (max={r.max_version_in_config})")
    print("")
    print("Counts:")
    for k, v in r.counts.items():
        print(f"  - {k}: {v}")
    print("")
    missing = [ref for ref, ok in r.existence.get("all", {}).items() if not ok]
    if missing:
        print(f"Missing referenced files ({len(missing)}):")
        for ref in missing[:60]:
            print(f"  - {ref}")
        if len(missing) > 60:
            print(f"  ... and {len(missing)-60} more")
    else:
        print("Missing referenced files: none")
    if r.warnings:
        print("")
        print("Warnings:")
        for w in r.warnings:
            print(f"  - {w}")


def _print_validate_human(rep: dict) -> None:
    print("== SingStar Disc Builder: VALIDATE ==")
    try:
        print(f"Input:        {rep.get('input_path')}")
        ex = rep.get('export_root') or ""
        if ex:
            print(f"Export root:  {ex}")
        prod = rep.get('product') or ""
        if prod:
            print(f"Product:      {prod}")
    except Exception:
        pass

    sev = str(rep.get('severity') or 'FAIL').upper()
    ok = bool(rep.get('ok'))
    print(f"Severity:     {sev} ({'ok' if ok else 'fail'})")
    try:
        summ = rep.get('summary') or ""
        if summ:
            print(f"Summary:      {summ}")
    except Exception:
        pass

    counts = rep.get('counts') or {}
    if isinstance(counts, dict) and counts:
        print("")
        print("Counts:")
        preferred = [
            'songs_xml_files',
            'numeric_song_folders',
            'banks_from_songs_xml',
            'melodies_chc_files',
            'texture_pages',
        ]
        for k in preferred:
            if k in counts:
                print(f"  - {k}: {counts.get(k)}")
        # Print any remaining keys (stable sort) but keep it short.
        extras = [k for k in sorted(counts.keys()) if k not in preferred]
        for k in extras[:12]:
            print(f"  - {k}: {counts.get(k)}")
        if len(extras) > 12:
            print(f"  ... and {len(extras) - 12} more")

    errs = rep.get('errors') or []
    if errs:
        print("")
        print(f"Errors ({len(errs)}):")
        for e in errs[:25]:
            if isinstance(e, dict):
                code = e.get('code') or 'ERROR'
                msg = e.get('message') or ''
                fix = e.get('fix') or ''
                print(f"  - [{code}] {msg}")
                if fix:
                    print(f"      Fix: {fix}")
        if len(errs) > 25:
            print(f"  ... and {len(errs) - 25} more")

    warns = rep.get('warnings') or []
    if warns:
        print("")
        print(f"Warnings ({len(warns)}):")
        for w in warns[:25]:
            if isinstance(w, dict):
                code = w.get('code') or 'WARN'
                msg = w.get('message') or ''
                fix = w.get('fix') or ''
                print(f"  - [{code}] {msg}")
                if fix:
                    print(f"      Fix: {fix}")
        if len(warns) > 25:
            print(f"  ... and {len(warns) - 25} more")

    missing_refs = rep.get('missing_refs') or []
    if missing_refs:
        try:
            missing_refs = [str(x) for x in missing_refs]
        except Exception:
            pass
        print("")
        print(f"Missing referenced files ({len(missing_refs)}):")
        for ref in missing_refs[:40]:
            print(f"  - {ref}")
        if len(missing_refs) > 40:
            print(f"  ... and {len(missing_refs) - 40} more")
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="spcdb_tool", description="SingStar Disc Builder (inspect/plan/merge for SingStar PS3 discs).")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="Inspect a disc/export folder (or a loose Export zip).")
    p_ins.add_argument("path", help="Path to extracted disc folder OR a loose Export folder OR a zip containing loose export files.")
    p_ins.add_argument("--json", action="store_true", help="Emit JSON report.")
    p_ins.set_defaults(func=_cmd_inspect)

    p_val = sub.add_parser("validate", help="Validate a disc/export folder and report issues.")
    p_val.add_argument(
        "path",
        help="Path to extracted disc folder OR a loose Export folder OR a zip containing loose export files.",
    )
    p_val.add_argument("--json", action="store_true", help="Emit JSON report.")
    p_val.set_defaults(func=_cmd_validate)

    p_plan = sub.add_parser("plan", help="Plan a merge (detect duplicates, choose donor max bank, compute counts).")
    p_plan.add_argument("--base", required=True, help="Path to extracted Base disc folder.")
    p_plan.add_argument("--donor", action="append", default=[], help="Path to extracted Donor disc folder (repeatable).")
    p_plan.add_argument("--target-version", type=int, default=6, help="Output bank version to build (default: 6).")
    p_plan.add_argument(
        "--collision-policy",
        choices=["fail", "prefer_base", "prefer_donor"],
        default="fail",
        help="How to handle duplicate song IDs (default: fail).",
    )
    p_plan.add_argument("--json", action="store_true", help="Emit JSON report.")
    p_plan.set_defaults(func=_cmd_plan)

    p_merge = sub.add_parser("merge", help="Build a new output Base folder (copy base, merge donors, write new XML/CHC).")
    p_merge.add_argument("--base", required=True, help="Path to extracted Base disc folder.")
    p_merge.add_argument("--donor", action="append", default=[], help="Path to extracted Donor disc folder (repeatable).")
    p_merge.add_argument("--out", required=True, help="Output folder to create (must not exist).")
    p_merge.add_argument("--target-version", type=int, default=6, help="Output bank version to build (default: 6).")
    p_merge.add_argument("--mode", choices=["update-required", "self-contained"], default="update-required", help="Errata mode (default: update-required).")
    p_merge.add_argument("--collision-policy", choices=["fail", "dedupe_identical"], default="fail", help="Duplicate song ID handling (default: fail).")
    p_merge.add_argument("--songlist-mode", choices=["union-by-name"], default="union-by-name", help="Songlist merge mode (default: union-by-name).")
    p_merge.add_argument("--json", action="store_true", help="Emit JSON stats on success.")
    p_merge.set_defaults(func=_cmd_merge)

    p_gui = sub.add_parser("gui", help="Launch the GUI (auto: Qt if available, else Tk).")
    p_gui.set_defaults(func=_cmd_gui)

    p_gui_tk = sub.add_parser("gui-tk", help="Launch the GUI (Tkinter).")
    p_gui_tk.set_defaults(func=_cmd_gui_tk)

    p_gui_qt = sub.add_parser("gui-qt", help="Launch the GUI (PySide6/Qt).")
    p_gui_qt.set_defaults(func=_cmd_gui_qt)

    p_qt_diag = sub.add_parser("qt-diag", help="Diagnose Qt/PySide6 startup (prints plugin/platform errors).")
    p_qt_diag.set_defaults(func=_cmd_qt_diag)

    p_sb = sub.add_parser("support-bundle", help="Export a privacy-safe support bundle zip (logs/settings/system info).")
    p_sb.add_argument("--out", default="", help="Output .zip path (default: ./spcdb_support_<timestamp>.zip).")
    p_sb.add_argument("--no-redact", action="store_true", help="Do not redact file paths (not recommended).")
    p_sb.add_argument("--json", action="store_true", help="Emit JSON result.")
    p_sb.set_defaults(func=_cmd_support_bundle)


    args = p.parse_args(argv)
    rv = args.func(args)
    if rv is None:
        return 0
    try:
        return int(rv)
    except Exception:
        return 1


def _stub(name: str) -> None:
    from . import __version__

    print(f"{name} is not implemented yet in v{__version__}.")


def _cmd_plan(args: argparse.Namespace) -> int:
    base_ri = resolve_input(args.base)
    donor_ris = [resolve_input(d) for d in (args.donor or [])]
    if not donor_ris:
        raise SystemExit("plan requires at least one --donor")

    rep = make_plan(
        base_ri=base_ri,
        donor_ris=donor_ris,
        target_version=int(args.target_version),
        collision_policy=str(args.collision_policy),
    )

    if args.json:
        print(dumps_pretty(rep))
    else:
        _print_plan_human(rep)
    # clean up any temp dirs (zips)
    if base_ri.temp_dir is not None:
        base_ri.temp_dir.cleanup()
    for ri in donor_ris:
        if ri.temp_dir is not None:
            ri.temp_dir.cleanup()
    return 0



def _cmd_merge(args: argparse.Namespace) -> int:
    base_ri = resolve_input(args.base)
    donor_ris = [resolve_input(d) for d in (args.donor or [])]
    if not donor_ris:
        raise SystemExit("merge requires at least one --donor")

    opts = MergeOptions(
        target_version=int(args.target_version),
        mode=str(args.mode),
        collision_policy=str(args.collision_policy),
        songlist_mode=str(args.songlist_mode),
        verbose=False,
    )

    try:
        stats = merge_build(
            base_ri=base_ri,
            donor_ris=donor_ris,
            out_dir=Path(args.out),
            opts=opts,
        )
    except MergeError as e:
        raise SystemExit(f"MERGE FAILED: {e}") from e
    finally:
        if base_ri.temp_dir is not None:
            base_ri.temp_dir.cleanup()
        for ri in donor_ris:
            if ri.temp_dir is not None:
                ri.temp_dir.cleanup()

    if args.json:
        print(dumps_pretty(stats))
    else:
        print("== SingStar Disc Builder MERGE ==")
        print(f"Output: {args.out}")
        print(f"Merged songs: {stats.merged_song_count} (base {stats.base_song_count} + donors {stats.donor_song_count})")
        print(f"Acts: {stats.acts_count}")
        print(f"Texture pages present: {stats.texture_pages_copied}")
        print(f"Banks written: 1..{opts.target_version} (melodies_{opts.target_version}.chc etc)")
        print("")
        print("Next: run `python -m spcdb_tool inspect <out>` and then test on hardware/emulator.")
    return 0

def _print_plan_human(r) -> None:
    print("== SingStar Disc Builder PLAN ==")
    print(f"Base:   {r.base.input_path}")
    print(f"        bank={r.base.chosen_bank} (max={r.base.max_bank}), songs={r.base.song_count}")
    for d in r.donors:
        print(f"Donor:  {d.input_path}")
        print(f"        bank={d.chosen_bank} (max={d.max_bank}), songs={d.song_count}")
    print("")
    print(f"Target output version: {r.target_version}")
    print(f"Merged song count (estimate): {r.merged_song_count}")
    print("")
    if r.collisions:
        print(f"Duplicate song IDs detected: {len(r.collisions)}")
        bad = [c for c in r.collisions if not c.identical]
        good = [c for c in r.collisions if c.identical]
        if good:
            print(f"  - identical (safe to de-dupe): {len(good)}")
        if bad:
            print(f"  - unresolved (likely unsafe): {len(bad)}")
            for c in bad[:40]:
                print(f"    * {c.song_id} (base fp={c.base_melody_fp or 'missing'}, donor fp={c.donor_melody_fp or 'missing'})")
            if len(bad) > 40:
                print(f"    ... and {len(bad)-40} more")
    else:
        print("Duplicate song IDs detected: none")
    if r.notes:
        print("")
        print("Notes:")
        for n in r.notes:
            print(f"  - {n}")
