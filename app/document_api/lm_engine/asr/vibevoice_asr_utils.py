"""VibeVoice ASR: โหลดเสียงด้วย librosa, stream token, หยุดเมื่อ heuristic หลอน."""
from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Sequence
from threading import Thread
from typing import Any

import librosa
import numpy as np
import torch
from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer


def detect_repetition_hallucination(content: str) -> dict:
    """เฮียริสติก: จับการซ้ำแบบหลอน (ใช้ทั้งระหว่าง stream กับหลัง parse)"""
    text = (content or "").strip()
    if len(text) < 8:
        return {"suspicious": False, "score": 0.0, "reasons": []}

    reasons: list[str] = []
    score = 0.0

    tokens = text.split()
    if len(tokens) >= 2:
        max_run = 1
        run = 1
        for k in range(1, len(tokens)):
            if tokens[k] == tokens[k - 1]:
                run += 1
                max_run = max(max_run, run)
            else:
                run = 1
        if max_run >= 6:
            reasons.append(f"คำ/วลีซ้ำติดกัน {max_run} ครั้ง (เกินเกณฑ์ 6)")
            score = max(score, min(0.3 + (max_run - 6) * 0.02, 1.0))

        for n in (2, 3, 4, 5):
            found = False
            i = 0
            while i + n * 5 <= len(tokens):
                phrase = tuple(tokens[i : i + n])
                j = i
                reps = 0
                while j + n <= len(tokens) and tuple(tokens[j : j + n]) == phrase:
                    reps += 1
                    j += n
                if reps >= 5:
                    clip = " ".join(phrase[:3]) + ("…" if len(phrase) > 3 else "")
                    reasons.append(f"บล็อกวลี ({n} คำ) ซ้ำต่อเนื่อง ~{reps} รอบ เช่น 「{clip}」")
                    score = max(score, min(0.4 + (reps - 5) * 0.03, 1.0))
                    found = True
                    break
                i += 1
            if found:
                break

        if len(tokens) >= 20:
            uniq_ratio = len(set(tokens)) / len(tokens)
            if uniq_ratio < 0.12:
                reasons.append(f"อัตราคำไม่ซ้ำต่ำมาก ({uniq_ratio:.0%} ของความยาว)")
                score = max(score, 0.55)

    def best_substring_stutter(s: str, min_l: int = 4, max_l: int = 48) -> int:
        best_c = 0
        L = len(s)
        if L < min_l * 4:
            return 0
        upper = min(max_l, L // 4)
        for size in range(min_l, upper + 1):
            for start in range(0, min(L - size, 400) + 1):
                piece = s[start : start + size]
                cnt = 1
                pos = start + size
                while pos + size <= L and s[pos : pos + size] == piece:
                    cnt += 1
                    pos += size
                if cnt > best_c:
                    best_c = cnt
        return best_c

    if len(text) >= 40:
        head = text[:2000]
        cnt = best_substring_stutter(head)
        if cnt >= 8:
            reasons.append(f"ช่วงตัวอักษรซ้ำต่อเนื่อง ~{cnt} ครั้ง (ใน {len(head)} ตัวแรก)")
            score = max(score, min(0.35 + (cnt - 8) * 0.04, 1.0))

    return {"suspicious": bool(reasons), "score": round(min(score, 1.0), 3), "reasons": reasons}


class StopOnHallucinationEvent(StoppingCriteria):
    """ให้ generate หยุดเมื่อ main thread set event (ตรวจหลอนระหว่าง stream)"""

    def __init__(self, stop_event: threading.Event):
        self.stop_event = stop_event

    def __call__(self, input_ids, scores, **kwargs) -> bool:
        return self.stop_event.is_set()


def load_audio_for_vibevoice(
    audio: str | np.ndarray | torch.Tensor,
    sampling_rate: int,
) -> np.ndarray:
    """โหลด path ด้วย librosa (หลีก torchcodec); numpy/torch คาดว่าเป็น mono แล้ว resample ถ้าไม่ตรง sr."""
    sr = int(sampling_rate)
    if isinstance(audio, str):
        w, _ = librosa.load(audio, sr=sr, mono=True)
        return w.astype(np.float32)
    if isinstance(audio, torch.Tensor):
        audio = audio.detach().float().cpu().numpy()
    w = np.asarray(audio, dtype=np.float32).reshape(-1)
    if w.size == 0:
        return w
    return w


def annotate_asr_segments(result: Any) -> tuple[Any, list[dict]]:
    """ถ้า parse ได้เป็น list[dict] ใส่ _hallucination ต่อ segment และคืนรายการที่ flagged"""
    if not isinstance(result, list):
        return result, []
    flagged: list[dict] = []
    out: list[Any] = []
    for i, seg in enumerate(result):
        if not isinstance(seg, dict):
            out.append(seg)
            continue
        info = detect_repetition_hallucination(str(seg.get("Content", "")))
        out.append({**seg, "_hallucination": info})
        if info["suspicious"]:
            flagged.append(
                {
                    "index": i,
                    "Start": seg.get("Start"),
                    "End": seg.get("End"),
                    "Speaker": seg.get("Speaker"),
                    **info,
                }
            )
    return out, flagged


def _decode_generated(processor: Any, gen_ids: torch.Tensor, decode_format: str, log: Any) -> tuple[Any, str]:
    if decode_format not in ("parsed", "raw"):
        raise ValueError("decode_format ต้องเป็น 'parsed' หรือ 'raw'")
    try:
        if decode_format == "parsed":
            return processor.decode(gen_ids, return_format="parsed")[0], "parsed"
        return processor.decode(gen_ids, return_format="raw")[0], "raw"
    except Exception as e:
        print(f"[decode] ใช้ raw แทน (มักเกิดเมื่อหยุดกลางคัน): {e}", file=log)
        return processor.decode(gen_ids, return_format="raw")[0], "raw"


def _transcribe_one(
    model: Any,
    processor: Any,
    audio: str | np.ndarray | torch.Tensor,
    *,
    prompt: str | None,
    max_new_tokens: int,
    stream: bool,
    stream_sink: Callable[[str], None] | None,
    stream_header: str | None,
    stream_footer: str | None,
    stop_on_hallucination: bool,
    hall_window: int,
    decode_format: str,
    log: Any,
    source_label: str | None,
) -> dict[str, Any]:
    log = sys.stderr if log is None else log
    sr = int(processor.feature_extractor.sampling_rate)
    waveform = load_audio_for_vibevoice(audio, sr)

    inputs = processor.apply_transcription_request(audio=waveform, prompt=prompt).to(
        model.device, model.dtype
    )
    prompt_len = int(inputs["input_ids"].shape[1])

    def default_sink(chunk: str) -> None:
        print(chunk, end="", flush=True)

    sink = stream_sink if stream_sink is not None else default_sink

    if not stream:
        output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)
        gen_ids = output_ids[:, prompt_len:]
        stream_text = processor.tokenizer.decode(gen_ids[0], skip_special_tokens=True)
        result, used = _decode_generated(processor, gen_ids, decode_format, log)
        row = {
            "result": result,
            "decode_format_used": used,
            "stream_text": stream_text,
            "stopped_by_hallucination": False,
            "hallucination": None,
            "output_ids": output_ids,
            "generated_ids": gen_ids,
        }
        if source_label is not None:
            row["source"] = source_label
        return row

    streamer = TextIteratorStreamer(
        processor.tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
    )
    stop_event = threading.Event()
    gen_kwargs = {
        **inputs,
        "streamer": streamer,
        "max_new_tokens": max_new_tokens,
    }
    if stop_on_hallucination:
        gen_kwargs["stopping_criteria"] = StoppingCriteriaList([StopOnHallucinationEvent(stop_event)])

    out_holder: dict[str, Any] = {}

    def _run_generate() -> None:
        out_holder["output_ids"] = model.generate(**gen_kwargs)

    thread = Thread(target=_run_generate, daemon=True)
    if stream_header is not None:
        print(stream_header, end="", flush=True)
    thread.start()

    stream_text = ""
    hallucination_hit: dict | None = None
    stopped_by_hallucination = False

    for chunk in streamer:
        sink(chunk)
        stream_text += chunk
        if stop_on_hallucination and len(stream_text) >= 50:
            win = stream_text[-hall_window:]
            h = detect_repetition_hallucination(win)
            if h["suspicious"]:
                hallucination_hit = h
                print("", file=log)
                print("⚠ [หลอน] หยุด generate ทันที:", file=log)
                for r in h["reasons"][:8]:
                    print("   ·", r, file=log)
                if len(h["reasons"]) > 8:
                    print("   · …", file=log)
                print(f"   score≈{h['score']}", file=log)
                stop_event.set()
                stopped_by_hallucination = True
                break

    if stream_footer is not None:
        print(stream_footer, end="", flush=True)
    thread.join()

    if stopped_by_hallucination:
        print("[หมายเหตุ] หยุดกลางคันเพราะ heuristic หลอน — JSON อาจไม่ครบ", file=log)

    output_ids = out_holder["output_ids"]
    gen_ids = output_ids[:, prompt_len:]
    result, used = _decode_generated(processor, gen_ids, decode_format, log)

    row = {
        "result": result,
        "decode_format_used": used,
        "stream_text": stream_text,
        "stopped_by_hallucination": stopped_by_hallucination,
        "hallucination": hallucination_hit,
        "output_ids": output_ids,
        "generated_ids": gen_ids,
    }
    if source_label is not None:
        row["source"] = source_label
    return row


def transcribe_audio_streaming(
    model: Any,
    processor: Any,
    audio: str | np.ndarray | torch.Tensor | Sequence[str],
    *,
    prompt: str | None = None,
    max_new_tokens: int = 8192,
    stream: bool = True,
    stream_sink: Callable[[str], None] | None = None,
    stream_header: str | None = "--- stream ---\n",
    stream_footer: str | None = "\n--- end stream ---\n",
    stop_on_hallucination: bool = True,
    hall_window: int = 2200,
    decode_format: str = "parsed",
    log: Any | None = None,
) -> list[dict[str, Any]]:
    """
    Transcribe ไฟล์หรือ waveform ด้วย VibeVoice ASR

    Returns:
        list[dict] — แต่ละ dict มี result, stream_text, stopped_by_hallucination, hallucination,
        decode_format_used, output_ids, generated_ids และถ้าเป็น path จะมี key ``source``
    """
    log = sys.stderr if log is None else log

    if isinstance(audio, (list, tuple)) and (not audio or all(isinstance(x, str) for x in audio)):
        if not audio:
            return []
        outs: list[dict[str, Any]] = []
        for i, path in enumerate(audio):
            if stream_header is not None and i > 0:
                print(f"--- stream ({path}) ---\n", end="", flush=True)
            outs.append(
                _transcribe_one(
                    model,
                    processor,
                    path,
                    prompt=prompt,
                    max_new_tokens=max_new_tokens,
                    stream=stream,
                    stream_sink=stream_sink,
                    stream_header=stream_header if i == 0 else None,
                    stream_footer=stream_footer,
                    stop_on_hallucination=stop_on_hallucination,
                    hall_window=hall_window,
                    decode_format=decode_format,
                    log=log,
                    source_label=path,
                )
            )
        return outs

    if isinstance(audio, (list, tuple)):
        raise TypeError(
            "ถ้า audio เป็น list/tuple ต้องเป็นลิสต์ของ path (str) เท่านั้น — waveform ส่งเป็น ndarray/tensor ตัวเดียว"
        )

    label = audio if isinstance(audio, str) else None
    return [
        _transcribe_one(
            model,
            processor,
            audio,
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            stream=stream,
            stream_sink=stream_sink,
            stream_header=stream_header,
            stream_footer=stream_footer,
            stop_on_hallucination=stop_on_hallucination,
            hall_window=hall_window,
            decode_format=decode_format,
            log=log,
            source_label=label,
        )
    ]
