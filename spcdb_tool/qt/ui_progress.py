# ruff: noqa
from __future__ import annotations

"""Qt progress / phase timing / ETA helpers.

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental refactor.
Behavior is intended to be unchanged.

These functions operate on the MainWindow instance (passed as `mw`).
"""

import json
import time
from typing import Optional


def start_op_clock(mw) -> None:
    try:
        mw._op_start_ts = float(time.monotonic())
    except Exception:
        mw._op_start_ts = None

    # Reset ETA state
    try:
        mw._eta_phase = None
        mw._eta_total = None
        mw._eta_current = None
        mw._eta_last_ts = None
        mw._eta_last_current = None
        mw._eta_spu_ema = None
        mw._eta_phase_start_ts = None
        mw._eta_indeterminate = True
        mw._eta_hist_current_key = None
        mw._eta_hist_phase_start_ts = None
    except Exception:
        pass

    try:
        if getattr(mw, "op_elapsed_lbl", None) is not None:
            mw.op_elapsed_lbl.setText("00:00")
        if getattr(mw, "op_eta_lbl", None) is not None:
            mw.op_eta_lbl.setText("—")
        if getattr(mw, "op_eta_title_lbl", None) is not None:
            mw.op_eta_title_lbl.setText("ETA:")
    except Exception:
        pass

    try:
        if getattr(mw, "_op_clock_timer", None) is not None and (not mw._op_clock_timer.isActive()):
            mw._op_clock_timer.start()
    except Exception:
        pass


def stop_op_clock(mw) -> None:
    try:
        eta_finalize_phase_tracking(mw)
    except Exception:
        pass

    try:
        if getattr(mw, "_op_clock_timer", None) is not None and mw._op_clock_timer.isActive():
            mw._op_clock_timer.stop()
    except Exception:
        pass

    try:
        mw._op_start_ts = None
    except Exception:
        pass

    try:
        mw._eta_phase = None
        mw._eta_total = None
        mw._eta_current = None
        mw._eta_last_ts = None
        mw._eta_last_current = None
        mw._eta_spu_ema = None
        mw._eta_phase_start_ts = None
        mw._eta_indeterminate = True
    except Exception:
        pass

    try:
        if getattr(mw, "op_elapsed_lbl", None) is not None:
            mw.op_elapsed_lbl.setText("")
        if getattr(mw, "op_eta_lbl", None) is not None:
            mw.op_eta_lbl.setText("")
        if getattr(mw, "op_eta_title_lbl", None) is not None:
            mw.op_eta_title_lbl.setText("ETA:")
    except Exception:
        pass


def tick_op_clock(mw) -> None:
    try:
        if not bool(getattr(mw, "_busy", False)):
            return
    except Exception:
        pass

    start = getattr(mw, "_op_start_ts", None)
    if start is None:
        return

    try:
        now = float(time.monotonic())
        if getattr(mw, "op_elapsed_lbl", None) is not None:
            mw.op_elapsed_lbl.setText(mw._fmt_duration(now - float(start)))
    except Exception:
        pass

    try:
        render_eta(mw)
    except Exception:
        pass


def eta_full_key(mw, phase: str) -> str:
    """Build a stable key for phase-duration heuristics."""
    try:
        op = str(getattr(mw, "_active_op", "") or "").strip()
    except Exception:
        op = ""
    ph = str(phase or "").strip()
    if op and ph:
        return f"{op}:{ph}"
    if ph:
        return ph
    return op or ""


def eta_record_phase_sample(mw, key: str, duration_sec: float) -> None:
    """Update the EMA duration for a phase key (heuristic ETA)."""
    k = str(key or "").strip()
    if not k:
        return
    try:
        dur = float(duration_sec)
    except Exception:
        return
    if dur < 0.5:
        return
    if dur > (24.0 * 60.0 * 60.0):
        return

    try:
        prev = (getattr(mw, "_eta_phase_ema_sec", {}) or {}).get(k, None)
    except Exception:
        prev = None

    alpha = 0.30
    if prev is None:
        ema = dur
    else:
        try:
            ema = (alpha * dur) + ((1.0 - alpha) * float(prev))
        except Exception:
            ema = dur

    try:
        mw._eta_phase_ema_sec[k] = float(ema)
        mw._eta_hist_dirty = True
    except Exception:
        pass


def eta_track_phase(mw, phase: str) -> None:
    """Track phase boundaries and record phase duration samples."""
    ph = str(phase or "").strip()
    if not ph:
        return
    try:
        now = float(time.monotonic())
    except Exception:
        return

    key = eta_full_key(mw, ph)

    try:
        cur_key = getattr(mw, "_eta_hist_current_key", None)
    except Exception:
        cur_key = None
    try:
        cur_start = getattr(mw, "_eta_hist_phase_start_ts", None)
    except Exception:
        cur_start = None

    if cur_key and (cur_start is not None):
        if str(cur_key) != str(key):
            try:
                eta_record_phase_sample(mw, str(cur_key), max(0.0, float(now) - float(cur_start)))
            except Exception:
                pass
            try:
                mw._eta_hist_current_key = str(key)
                mw._eta_hist_phase_start_ts = float(now)
            except Exception:
                pass
            return

    # First phase start
    try:
        if getattr(mw, "_eta_hist_current_key", None) is None:
            mw._eta_hist_current_key = str(key)
            mw._eta_hist_phase_start_ts = float(now)
    except Exception:
        pass


def eta_finalize_phase_tracking(mw) -> None:
    """Finalize in-flight phase timing on op end and persist EMA values if changed."""
    try:
        now = float(time.monotonic())
    except Exception:
        now = None

    try:
        cur_key = getattr(mw, "_eta_hist_current_key", None)
    except Exception:
        cur_key = None
    try:
        cur_start = getattr(mw, "_eta_hist_phase_start_ts", None)
    except Exception:
        cur_start = None

    if cur_key and (cur_start is not None) and (now is not None):
        try:
            eta_record_phase_sample(mw, str(cur_key), max(0.0, float(now) - float(cur_start)))
        except Exception:
            pass

    try:
        mw._eta_hist_current_key = None
        mw._eta_hist_phase_start_ts = None
    except Exception:
        pass

    try:
        if bool(getattr(mw, "_eta_hist_dirty", False)):
            mw._save_qt_state(force=True)
            mw._eta_hist_dirty = False
    except Exception:
        pass


def render_eta_indeterminate(mw) -> None:
    """Render ETA for indeterminate phases using heuristics when available."""
    if not bool(getattr(mw, "_busy", False)):
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("")
            if getattr(mw, "op_eta_title_lbl", None) is not None:
                mw.op_eta_title_lbl.setText("ETA:")
        except Exception:
            pass
        return

    try:
        now = float(time.monotonic())
    except Exception:
        now = None

    try:
        key = getattr(mw, "_eta_hist_current_key", None)
    except Exception:
        key = None
    if not key:
        try:
            key = eta_full_key(mw, str(getattr(mw, "_eta_phase", "") or ""))
        except Exception:
            key = ""

    try:
        expected = (getattr(mw, "_eta_phase_ema_sec", {}) or {}).get(str(key), None)
    except Exception:
        expected = None

    start_ts = None
    try:
        start_ts = getattr(mw, "_eta_hist_phase_start_ts", None)
    except Exception:
        start_ts = None
    if start_ts is None:
        try:
            start_ts = getattr(mw, "_eta_phase_start_ts", None)
        except Exception:
            start_ts = None

    if (expected is None) or (now is None) or (start_ts is None):
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("—")
            if getattr(mw, "op_eta_title_lbl", None) is not None:
                mw.op_eta_title_lbl.setText("ETA:")
        except Exception:
            pass
        return

    try:
        exp_f = float(expected)
    except Exception:
        exp_f = None
    if exp_f is None or exp_f <= 0.5:
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("—")
            if getattr(mw, "op_eta_title_lbl", None) is not None:
                mw.op_eta_title_lbl.setText("ETA:")
        except Exception:
            pass
        return

    try:
        elapsed = max(0.0, float(now) - float(start_ts))
    except Exception:
        elapsed = 0.0

    remaining = float(max(0.0, float(exp_f) - float(elapsed)))
    try:
        if getattr(mw, "op_eta_lbl", None) is not None:
            mw.op_eta_lbl.setText(mw._fmt_duration(remaining))
        if getattr(mw, "op_eta_title_lbl", None) is not None:
            mw.op_eta_title_lbl.setText("ETA (est):")
    except Exception:
        pass


def update_eta_state(
    mw,
    *,
    phase: str,
    current: Optional[int],
    total: Optional[int],
    indeterminate: bool,
) -> None:
    now = float(time.monotonic())

    if bool(indeterminate) or (current is None) or (total is None):
        mw._eta_indeterminate = True
        mw._eta_current = None
        mw._eta_total = None
        phase_key = str(phase or "")
        try:
            if (getattr(mw, "_eta_phase", None) != phase_key) or (getattr(mw, "_eta_phase_start_ts", None) is None):
                mw._eta_phase_start_ts = now
        except Exception:
            mw._eta_phase_start_ts = now
        mw._eta_phase = phase_key
        mw._eta_last_ts = None
        mw._eta_last_current = None
        mw._eta_spu_ema = None
        try:
            render_eta(mw)
        except Exception:
            pass
        return

    try:
        cur_i = int(current)
    except Exception:
        cur_i = 0
    try:
        tot_i = int(total)
    except Exception:
        tot_i = 0

    if tot_i <= 0:
        mw._eta_indeterminate = True
        mw._eta_current = None
        mw._eta_total = None
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("—" if bool(getattr(mw, "_busy", False)) else "")
        except Exception:
            pass
        return

    phase_key = str(phase or "")

    needs_reset = False
    if mw._eta_phase != phase_key:
        needs_reset = True
    if (mw._eta_total is not None) and (int(mw._eta_total) != int(tot_i)):
        needs_reset = True
    if (mw._eta_current is not None) and (int(cur_i) < int(mw._eta_current)):
        needs_reset = True

    if needs_reset:
        mw._eta_phase = phase_key
        mw._eta_total = int(tot_i)
        mw._eta_current = int(cur_i)
        mw._eta_phase_start_ts = now
        mw._eta_last_ts = now
        mw._eta_last_current = int(cur_i)
        mw._eta_spu_ema = None
        mw._eta_indeterminate = False
        render_eta(mw)
        return

    # Update EMA of seconds-per-unit based on progress deltas.
    try:
        last_ts = float(mw._eta_last_ts) if (mw._eta_last_ts is not None) else None
    except Exception:
        last_ts = None
    try:
        last_cur = int(mw._eta_last_current) if (mw._eta_last_current is not None) else None
    except Exception:
        last_cur = None

    if last_ts is not None and last_cur is not None:
        dt = max(0.0, now - last_ts)
        dc = int(cur_i) - int(last_cur)
        if dt >= 0.2 and dc > 0:
            sample_spu = float(dt) / float(dc)
            if mw._eta_spu_ema is None:
                mw._eta_spu_ema = float(sample_spu)
            else:
                alpha = 0.25
                mw._eta_spu_ema = (alpha * float(sample_spu)) + ((1.0 - alpha) * float(mw._eta_spu_ema))

    mw._eta_indeterminate = False
    mw._eta_total = int(tot_i)
    mw._eta_current = int(cur_i)
    mw._eta_last_ts = now
    mw._eta_last_current = int(cur_i)

    render_eta(mw)


def render_eta(mw) -> None:
    if not bool(getattr(mw, "_busy", False)):
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("")
        except Exception:
            pass
        return

    if bool(getattr(mw, "_eta_indeterminate", True)) or (getattr(mw, "_eta_current", None) is None) or (getattr(mw, "_eta_total", None) is None):
        try:
            render_eta_indeterminate(mw)
        except Exception:
            pass
        return

    try:
        if getattr(mw, "op_eta_title_lbl", None) is not None:
            mw.op_eta_title_lbl.setText("ETA:")
    except Exception:
        pass

    try:
        cur_i = int(getattr(mw, "_eta_current", 0) or 0)
    except Exception:
        cur_i = 0
    try:
        tot_i = int(getattr(mw, "_eta_total", 0) or 0)
    except Exception:
        tot_i = 0

    if tot_i <= 0:
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("—")
        except Exception:
            pass
        return

    if cur_i >= tot_i:
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("00:00")
        except Exception:
            pass
        return

    if cur_i <= 0:
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("—")
        except Exception:
            pass
        return

    now = float(time.monotonic())
    phase_start = getattr(mw, "_eta_phase_start_ts", None)
    if phase_start is None:
        phase_elapsed = None
    else:
        try:
            phase_elapsed = max(0.0, now - float(phase_start))
        except Exception:
            phase_elapsed = None

    spu = None
    try:
        if getattr(mw, "_eta_spu_ema", None) is not None:
            spu = float(getattr(mw, "_eta_spu_ema"))
    except Exception:
        spu = None

    if spu is None and phase_elapsed is not None and cur_i > 0:
        spu = float(phase_elapsed) / float(cur_i)

    if spu is None:
        try:
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("—")
        except Exception:
            pass
        return

    remaining = float(max(0.0, (tot_i - cur_i) * float(spu)))
    try:
        if getattr(mw, "op_eta_lbl", None) is not None:
            mw.op_eta_lbl.setText(mw._fmt_duration(remaining))
    except Exception:
        pass


def reset_progress_ui(mw) -> None:
    try:
        mw.op_phase_lbl.setText("Idle")
        mw.op_detail_lbl.setText("")
        mw.op_progress.setVisible(False)
        mw.op_progress.setRange(0, 100)
        mw.op_progress.setValue(0)
        try:
            if getattr(mw, "op_elapsed_lbl", None) is not None:
                mw.op_elapsed_lbl.setText("")
            if getattr(mw, "op_eta_lbl", None) is not None:
                mw.op_eta_lbl.setText("")
            if getattr(mw, "op_eta_title_lbl", None) is not None:
                mw.op_eta_title_lbl.setText("ETA:")
        except Exception:
            pass
        try:
            stop_op_clock(mw)
        except Exception:
            pass
    except Exception:
        pass


def set_progress_ui(
    mw,
    *,
    phase: str,
    detail: str = "",
    current: Optional[int] = None,
    total: Optional[int] = None,
    indeterminate: bool = False,
) -> None:
    try:
        mw.op_phase_lbl.setText(str(phase or ""))
        mw.op_detail_lbl.setText(str(detail or ""))

        # Only show progress while an op is active.
        mw.op_progress.setVisible(bool(mw._busy))

        if indeterminate or (current is None) or (total is None):
            # Qt indeterminate
            mw.op_progress.setRange(0, 0)
        else:
            t = max(1, int(total))
            c = max(0, min(int(current), t))
            mw.op_progress.setRange(0, t)
            mw.op_progress.setValue(c)
        try:
            if bool(getattr(mw, '_busy', False)) and (getattr(mw, '_op_start_ts', None) is None):
                start_op_clock(mw)
        except Exception:
            pass
        try:
            eta_track_phase(mw, str(phase or ""))
        except Exception:
            pass
        try:
            update_eta_state(
                mw,
                phase=str(phase or ''),
                current=current,
                total=total,
                indeterminate=bool(indeterminate) or (current is None) or (total is None),
            )
        except Exception:
            pass
    except Exception:
        pass


def map_build_phase_group(raw_phase: str) -> str:
    p = str(raw_phase or "").strip().lower()
    if p in {"copy", "prune"}:
        return "Copy"
    if p in {"finalize", "done"}:
        return "Finalize"
    if p in {"import", "copy songs", "textures", "write", "melody", "chc", "config"}:
        return "Merge"
    # Unknown phase: show as-is.
    return str(raw_phase or "")


def handle_structured_progress(mw, payload_text: str) -> None:
    try:
        payload = json.loads(str(payload_text or ""))
    except Exception:
        return

    raw_phase = str((payload or {}).get("phase", "") or "")
    msg = str((payload or {}).get("message", "") or "")
    ind = bool((payload or {}).get("indeterminate", False))

    cur = (payload or {}).get("current", None)
    tot = (payload or {}).get("total", None)
    try:
        cur_i = int(cur) if cur is not None else None
    except Exception:
        cur_i = None
    try:
        tot_i = int(tot) if tot is not None else None
    except Exception:
        tot_i = None

    group = map_build_phase_group(raw_phase)
    detail = msg
    if group != raw_phase and raw_phase:
        detail = f"{raw_phase}: {msg}" if msg else str(raw_phase)

    set_progress_ui(
        mw,
        phase=group or "Build",
        detail=detail,
        current=cur_i,
        total=tot_i,
        indeterminate=bool(ind),
    )
