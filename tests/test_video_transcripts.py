from blackboard_mcp.video_transcripts import (
    extract_kaltura_ids, parse_vtt_cues, parse_vtt_playlist, select_ready_caption_asset,
)

_REAL_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-TARGETDURATION:300\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-MEDIA-SEQUENCE:1\n"
    "#EXT-X-PLAYLIST-TYPE:VOD\n"
    "#EXTINF:300.0,\n"
    "segmentIndex/1.vtt\n"
    "#EXTINF:300.0,\n"
    "segmentIndex/2.vtt\n"
    "#EXTINF:159.0,\n"
    "segmentIndex/3.vtt\n"
    "#EXT-X-ENDLIST\n"
)

_REAL_VTT_SEGMENT = (
    "WEBVTT\n\n"
    "00:00:08.070 --> 00:00:11.040\n"
    "&gt;&gt;Olá pessoal sejam bem-vindos\n"
    "a mais à rede o lá, eu sou\n\n"
    "00:00:11.050 --> 00:00:14.580\n"
    "professor Alberto, vamos falar\n"
    "então sobre os conceitos de Big\n\n"
    "00:00:14.590 --> 00:00:15.390\n"
    "data.\n"
)


def test_parses_the_real_playlist_shape_into_ordered_segment_paths() -> None:
    assert parse_vtt_playlist(_REAL_PLAYLIST) == [
        "segmentIndex/1.vtt", "segmentIndex/2.vtt", "segmentIndex/3.vtt",
    ]


def test_playlist_with_no_segments_yields_empty_list() -> None:
    assert parse_vtt_playlist("#EXTM3U\n#EXT-X-ENDLIST\n") == []


def test_playlist_rejects_a_kaltura_api_error_body() -> None:
    """Real incident (2026-09-04): a malformed request URL made Kaltura
    answer `200 OK` with an XML `INVALID_KS` error instead of a real
    playlist — every line of that XML would otherwise be misread as a
    segment path to fetch next."""
    xml_error = '<?xml version="1.0" encoding="utf-8"?><xml><result><error>...'
    assert parse_vtt_playlist(xml_error) == []


def test_parses_real_captions_into_continuous_text_without_timestamps() -> None:
    text = parse_vtt_cues(_REAL_VTT_SEGMENT)
    assert ">>Olá pessoal sejam bem-vindos a mais à rede o lá, eu sou" in text
    assert "professor Alberto, vamos falar então sobre os conceitos de Big data." in text
    assert "-->" not in text
    assert "WEBVTT" not in text


def test_strips_a_leading_numeric_cue_id_line() -> None:
    """Some VTT producers number each cue before its timestamp line —
    without stripping it, a bare "1" would leak into the transcript text."""
    vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nOlá.\n"
    assert parse_vtt_cues(vtt) == "Olá."


def test_empty_segment_yields_empty_string() -> None:
    assert parse_vtt_cues("WEBVTT\n") == ""


def test_cues_rejects_a_kaltura_api_error_body() -> None:
    xml_error = '<?xml version="1.0" encoding="utf-8"?><xml><result><error>...'
    assert parse_vtt_cues(xml_error) == ""


def test_extracts_entry_and_partner_id_from_the_embed_bootstrap_url() -> None:
    url = (
        "https://cdnapisec.kaltura.com/p/1756931/embedPlaykitJs/uiconf_id/51054902"
        "?iframeembed=true&playerId=kaltura_player_1534527969&entry_id=1_2073pngi"
    )
    assert extract_kaltura_ids(url) == ("1_2073pngi", "1756931")


def test_extracts_ids_from_the_path_style_cdn_url() -> None:
    url = "https://cdnsecakmi.kaltura.com/p/1756931/sp/175693100/thumbnail/entry_id/1_2073pngi/version/1"
    entry_id, partner_id = extract_kaltura_ids(url)
    assert partner_id == "1756931"


def test_extract_kaltura_ids_returns_none_for_an_unrelated_url() -> None:
    assert extract_kaltura_ids("https://example.com/nothing") == (None, None)


_READY_CAPTION = {"id": "1_72783sh9", "entryId": "1_2073pngi", "status": 2, "isDefault": False, "language": "Portuguese"}
_DELETED_CAPTION = {"id": "1_qbxvaga0", "entryId": "1_2073pngi", "status": -1, "isDefault": False}


def test_select_ready_caption_asset_skips_deleted_ones() -> None:
    """Real incident (2026-09-04): Kaltura keeps a soft-deleted caption asset
    (`status: -1`) in the SAME list as the real one — picking the wrong entry
    would silently fetch nothing useful (a deleted asset's VTT is gone)."""
    assert select_ready_caption_asset([_DELETED_CAPTION, _READY_CAPTION]) == _READY_CAPTION


def test_select_ready_caption_asset_prefers_the_default_one() -> None:
    other_ready = {**_READY_CAPTION, "id": "1_other", "isDefault": True}
    assert select_ready_caption_asset([_READY_CAPTION, other_ready]) == other_ready


def test_select_ready_caption_asset_returns_none_when_nothing_is_ready() -> None:
    assert select_ready_caption_asset([_DELETED_CAPTION]) is None


def test_select_ready_caption_asset_returns_none_for_empty_list() -> None:
    assert select_ready_caption_asset([]) is None
