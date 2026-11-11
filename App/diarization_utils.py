"""Speaker-attribution helpers for diarized audio.

Deliberately dependency-free and side-effect free: the mapping logic is pure so
it can be unit-tested without loading any speech model, and so it can be reused
for both provider diarization (OpenAI ``diarized_json``) and any future local
diarizer.

Segment shape (see ``llm_manager._normalize_stt_segments``)::

    {'start': float seconds, 'end': float seconds, 'text': str, 'speaker': str|None}

Message shape (from session JSON)::

    {'source_text': str, 'translated_text': str, 'offset_ms': int|None,
     'timestamp': ISO-8601 str, 'speaker': str|None, ...}
"""


def _as_float(value):
    """Best-effort numeric conversion; returns None when not numeric."""
    # bools are ints in Python and never meaningful here.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _usable_segments(segments):
    """Filter to segments carrying both a speaker and a real time span."""
    usable = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        start = _as_float(seg.get('start'))
        end = _as_float(seg.get('end'))
        speaker = seg.get('speaker')
        if start is None or end is None or speaker is None:
            continue
        speaker = str(speaker).strip()
        if not speaker:
            continue
        if end < start:
            start, end = end, start
        usable.append((start, end, speaker))
    usable.sort(key=lambda item: item[0])
    return usable


def _nearest_speaker(seconds, segments):
    """Speaker of the segment closest to ``seconds`` (covers timeline gaps)."""
    best_speaker = None
    best_distance = None
    for start, end, speaker in segments:
        if seconds < start:
            distance = start - seconds
        elif seconds > end:
            distance = seconds - end
        else:
            distance = 0.0
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_speaker = speaker
    return best_speaker


def _synthetic_offsets(count, segments):
    """Spread messages evenly across the recording when no offsets exist.

    Covers sessions recorded before ``offset_ms`` was stored: the messages are
    in spoken order, so mapping them proportionally onto the diarized timeline
    is the best available approximation.
    """
    if count <= 0 or not segments:
        return [None] * max(count, 0)
    span_start = segments[0][0]
    span_end = segments[-1][1]
    if span_end <= span_start:
        return [int(span_start * 1000)] * count
    step = (span_end - span_start) / count
    return [int((span_start + step * (index + 0.5)) * 1000) for index in range(count)]


def _fill_missing_offsets(offsets):
    """Fill gaps in a partially populated offset list from the nearest sample."""
    known = [(index, offset) for index, offset in enumerate(offsets) if offset is not None]
    if not known:
        return list(offsets)
    filled = list(offsets)
    for index, offset in enumerate(filled):
        if offset is not None:
            continue
        nearest = min(known, key=lambda item: abs(item[0] - index))
        filled[index] = nearest[1]
    return filled


def assign_speakers(messages, segments):
    """Align diarized segments onto session messages.

    Messages are matched by ``offset_ms`` (milliseconds into the recording)
    against each segment's ``start``/``end`` (seconds). Messages without an
    offset are interpolated from their neighbours, or spread proportionally
    across the recording when the session has no offsets at all.

    Returns ``(message, speaker)`` tuples in the original message order.
    ``speaker`` is None when nothing could be matched, which callers should
    treat as "leave the existing attribution alone".
    """
    message_list = list(messages or [])
    if not message_list:
        return []

    usable = _usable_segments(segments)
    if not usable:
        return [(message, None) for message in message_list]

    offsets = [_as_float(message.get('offset_ms')) for message in message_list]
    if all(offset is None for offset in offsets):
        offsets = _synthetic_offsets(len(message_list), usable)
    else:
        offsets = _fill_missing_offsets(offsets)

    assignments = []
    for message, offset_ms in zip(message_list, offsets):
        speaker = None
        if offset_ms is not None:
            seconds = offset_ms / 1000.0
            for start, end, segment_speaker in usable:
                if start <= seconds < end:
                    speaker = segment_speaker
                    break
            if speaker is None:
                speaker = _nearest_speaker(seconds, usable)
        assignments.append((message, speaker))
    return assignments


def speaker_index_map(assignments):
    """Convert assign_speakers() output into {message_index: speaker}."""
    mapping = {}
    for index, (_, speaker) in enumerate(assignments or []):
        if speaker:
            mapping[index] = speaker
    return mapping
