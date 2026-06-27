"""Regression: transcript merge dedupes optimistic rows against server history."""

from pathlib import Path


def test_app_uses_transcript_merge_for_history_and_sync():
    src = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    assert "mergeLocalAndServerTranscript" in src
    assert "dedupeTranscriptMessages" in src
    load_start = src.index("const loadHistory = async () => {")
    load_end = src.index("loadHistory();", load_start)
    load_block = src[load_start:load_end]
    assert "mergeLocalAndServerTranscript" in load_block
    assert "newServerMessages" not in load_block, (
        "loadHistory must not append server rows by id only"
    )
    sync_start = src.index("const syncSessionMessagesAfterStream = useCallback(")
    sync_end = src.index("const resumeHermesSessionStream = useCallback(", sync_start)
    sync_block = src[sync_start:sync_end]
    assert "mergeLocalAndServerTranscript" in sync_block


def test_transcript_merge_matches_legacy_dedupe():
    src = Path("frontend/src/features/chat/utils/transcriptMerge.ts").read_text(
        encoding="utf-8"
    )
    assert "sameTranscriptMessage" in src
    assert "stripAttachedFilesMarker" in src
    assert "mergeLocalAndServerTranscript" in src
    pending = Path(
        "frontend/src/features/chat/utils/sessionStreamReattach.ts"
    ).read_text(encoding="utf-8")
    assert "sameTranscriptMessage" in pending
