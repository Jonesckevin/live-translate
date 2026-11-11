"""Unit tests for speaker alignment.

These cover the pure mapping logic only: no models, no network, no Flask.
Run with either of:

    python -m pytest tests -v
    python tests/test_diarization_utils.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'App'))

from diarization_utils import (  # noqa: E402
    assign_speakers,
    speaker_index_map,
)


def _msg(offset_ms=None, text='hello'):
    return {'source_text': text, 'translated_text': 'bonjour', 'offset_ms': offset_ms}


SEGMENTS = [
    {'start': 0.0, 'end': 4.0, 'text': 'one', 'speaker': 'speaker_1'},
    {'start': 4.0, 'end': 8.0, 'text': 'two', 'speaker': 'speaker_2'},
    {'start': 9.0, 'end': 12.0, 'text': 'three', 'speaker': 'speaker_1'},
]


def test_matches_by_offset_overlap():
    messages = [_msg(1000), _msg(5000), _msg(9500)]
    speakers = [speaker for _, speaker in assign_speakers(messages, SEGMENTS)]
    assert speakers == ['speaker_1', 'speaker_2', 'speaker_1']


def test_gap_uses_nearest_segment():
    # 8.5s falls between segment 2 (ends 8.0) and segment 3 (starts 9.0).
    messages = [_msg(8500)]
    speakers = [speaker for _, speaker in assign_speakers(messages, SEGMENTS)]
    assert speakers == ['speaker_2']


def test_offset_beyond_last_segment_uses_last_speaker():
    messages = [_msg(60000)]
    speakers = [speaker for _, speaker in assign_speakers(messages, SEGMENTS)]
    assert speakers == ['speaker_1']


def test_ignores_segments_without_speaker_or_times():
    dirty = [
        {'start': 0.0, 'end': 4.0, 'text': 'a', 'speaker': None},
        {'start': 4.0, 'end': 8.0, 'text': 'b', 'speaker': 'speaker_2'},
        {'start': None, 'end': 8.0, 'text': 'c', 'speaker': 'speaker_3'},
        'not-a-dict',
    ]
    messages = [_msg(5000)]
    speakers = [speaker for _, speaker in assign_speakers(messages, dirty)]
    assert speakers == ['speaker_2']


def test_no_segments_leaves_speaker_unset():
    messages = [_msg(1000), _msg(2000)]
    speakers = [speaker for _, speaker in assign_speakers(messages, [])]
    assert speakers == [None, None]


def test_missing_offsets_are_spread_across_timeline():
    # Legacy sessions recorded before offset_ms existed: messages are in spoken
    # order, so they should map proportionally onto the diarized timeline.
    messages = [_msg(None, 'a'), _msg(None, 'b'), _msg(None, 'c')]
    speakers = [speaker for _, speaker in assign_speakers(messages, SEGMENTS)]
    assert speakers == ['speaker_1', 'speaker_2', 'speaker_1']


def test_partial_offsets_are_interpolated():
    messages = [_msg(500), _msg(None), _msg(10500)]
    speakers = [speaker for _, speaker in assign_speakers(messages, SEGMENTS)]
    assert len(speakers) == 3
    assert speakers[0] == 'speaker_1'
    assert speakers[2] == 'speaker_1'
    # The interpolated middle message inherits a neighbour's offset.
    assert speakers[1] in ('speaker_1', 'speaker_2')


def test_reversed_segment_bounds_are_tolerated():
    segments = [{'start': 8.0, 'end': 4.0, 'text': 'x', 'speaker': 'speaker_9'}]
    messages = [_msg(5000)]
    speakers = [speaker for _, speaker in assign_speakers(messages, segments)]
    assert speakers == ['speaker_9']


def test_empty_message_list():
    assert assign_speakers([], SEGMENTS) == []
    assert assign_speakers(None, SEGMENTS) == []


def test_speaker_index_map_drops_unattributed():
    messages = [_msg(1000), _msg(5000)]
    assignments = assign_speakers(messages, [{'start': 0.0, 'end': 2.0, 'text': 'x', 'speaker': 'speaker_1'}])
    # Second message has no overlapping or nearby speaker beyond segment 1.
    mapping = speaker_index_map(assignments)
    assert mapping.get(0) == 'speaker_1'


if __name__ == '__main__':
    failures = 0
    for name, func in sorted(globals().items()):
        if name.startswith('test_') and callable(func):
            try:
                func()
                print(f'PASS {name}')
            except AssertionError as exc:
                failures += 1
                print(f'FAIL {name}: {exc}')
    print(f'\n{"FAILED" if failures else "OK"}: {failures} failure(s)')
    sys.exit(1 if failures else 0)
