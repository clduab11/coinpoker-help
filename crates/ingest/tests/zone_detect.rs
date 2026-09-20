//! Zone-masked change detection over recorded frame fixtures.
//!
//! Loads synthetic table frames (a plain green felt with distinct colored
//! blocks in the pot, board, and action regions) and verifies that the
//! perceptual-hash zone detector reports changes in exactly the zone that
//! changed. No live game, screen capture, or VLM server is required.

use ingest::capture::Frame;
use ingest::change_detect::{Zone, ZoneChangeDetector, ZoneChangeDetectorConfig};

const BASELINE: &[u8] = include_bytes!("fixtures/table_baseline.png");
const IDENTICAL: &[u8] = include_bytes!("fixtures/table_identical.png");
const POT_CHANGED: &[u8] = include_bytes!("fixtures/table_pot_changed.png");
const BOARD_CHANGED: &[u8] = include_bytes!("fixtures/table_board_changed.png");
const ACTION_CHANGED: &[u8] = include_bytes!("fixtures/table_action_changed.png");

/// Decode a fixture PNG into a validated frame.
fn load_frame(png: &[u8]) -> Frame {
    let image = image::load_from_memory(png)
        .expect("fixture is a valid PNG")
        .to_rgba8();
    Frame::new(image.width(), image.height(), image.into_raw())
        .expect("fixture frame has consistent dimensions")
}

#[test]
fn fixtures_decode_to_the_expected_table_size() {
    for png in [
        BASELINE,
        IDENTICAL,
        POT_CHANGED,
        BOARD_CHANGED,
        ACTION_CHANGED,
    ] {
        let frame = load_frame(png);
        assert_eq!((frame.width, frame.height), (96, 64));
        assert!(frame.validate().is_ok());
    }
}

#[test]
fn first_frame_is_changed_and_identical_frames_are_not() {
    let mut detector = ZoneChangeDetector::new(ZoneChangeDetectorConfig::default());

    assert!(detector.detect(&load_frame(BASELINE)).changed);
    let result = detector.detect(&load_frame(IDENTICAL));
    assert!(!result.changed);
    assert!(!result.zone_changed(Zone::Pot));
    assert!(!result.zone_changed(Zone::Board));
    assert!(!result.zone_changed(Zone::Action));
}

#[test]
fn pot_zone_change_triggers_only_the_pot_zone() {
    let mut detector = ZoneChangeDetector::new(ZoneChangeDetectorConfig::default());
    assert!(detector.detect(&load_frame(BASELINE)).changed);

    let result = detector.detect(&load_frame(POT_CHANGED));
    assert!(result.changed);
    assert!(result.zone_changed(Zone::Pot));
    assert!(!result.zone_changed(Zone::Board));
    assert!(!result.zone_changed(Zone::Action));
}

#[test]
fn board_zone_change_triggers_only_the_board_zone() {
    let mut detector = ZoneChangeDetector::new(ZoneChangeDetectorConfig::default());
    assert!(detector.detect(&load_frame(BASELINE)).changed);

    let result = detector.detect(&load_frame(BOARD_CHANGED));
    assert!(result.changed);
    assert!(result.zone_changed(Zone::Board));
    assert!(!result.zone_changed(Zone::Pot));
    assert!(!result.zone_changed(Zone::Action));
}

#[test]
fn action_zone_change_triggers_only_the_action_zone() {
    let mut detector = ZoneChangeDetector::new(ZoneChangeDetectorConfig::default());
    assert!(detector.detect(&load_frame(BASELINE)).changed);

    let result = detector.detect(&load_frame(ACTION_CHANGED));
    assert!(result.changed);
    assert!(result.zone_changed(Zone::Action));
    assert!(!result.zone_changed(Zone::Pot));
    assert!(!result.zone_changed(Zone::Board));
}

#[test]
fn malformed_frame_fails_safe_and_keeps_the_good_baseline() {
    let mut detector = ZoneChangeDetector::new(ZoneChangeDetectorConfig::default());
    let baseline = load_frame(BASELINE);
    assert!(detector.detect(&baseline).changed);

    let malformed = Frame {
        width: 96,
        height: 64,
        rgba: vec![0; 15],
    };
    let result = detector.detect(&malformed);
    assert!(result.changed);
    assert!(result.zone_changed(Zone::Pot));

    // The known-good baseline survives the malformed frame.
    let result = detector.detect(&baseline);
    assert!(!result.changed);
}
