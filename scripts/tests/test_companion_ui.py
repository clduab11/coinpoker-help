"""Synthetic Node DOM contracts, not recognition or desktop geometry tests."""

import copy
import json
import shutil
import subprocess
import unittest

from scripts.tests import test_laya_dashboard_stage2 as stage2
from scripts.tests import test_laya_dashboard as native


CHECKS = r"""
const readingsCleared = () => {
  assert(!visible()); assert(nodes.get('suggested-action').hidden);
  for (const id of ['amount-pot', 'amount-stack', 'amount-call', 'acting-seat', 'game-phase']) {
    assert.equal(nodes.get(id).textContent, '-', id);
  }
  assert.equal(nodes.get('hero-cards').textContent, '-');
  assert.equal(nodes.get('board-cards').childNodes.length, 5);
  assert(nodes.get('board-cards').childNodes.every(card => card.classList.contains('unknown-card')));
  assert.equal(nodes.get('seat-readings').childNodes.length, 6);
  assert(!nodes.get('monitor-readings').hidden);
  assert(nodes.get('seat-readings').childNodes.every(seat => seat.textContent.includes('Seat status pending')));
  assert(nodes.get('metrics-readings').hidden); assert(nodes.get('action-amount-wrap').hidden);
};
for (const [id, expected] of Object.entries(input.expected || {})) {
  assert(nodes.get(id).textContent.includes(expected), `${id}: ${nodes.get(id).textContent}`);
}
if (input.scenario === 'literal') {
  assert.equal(nodes.get('amount-pot').textContent, '123.45');
  assert(nodes.get('seat-readings').childNodes[0].textContent.includes('1.0'));
  assert(nodes.get('seat-readings').childNodes[2].textContent.includes('Occluded'));
  assert(nodes.get('seat-readings').childNodes[3].textContent.includes('0.00 chips'));
  assert(!nodes.get('field-diagnostics').textContent.includes('PRIVATE'));
} else if (input.scenario === 'recording') {
  assert(nodes.get('recorder-status').textContent.includes('capturing'));
  assert(nodes.get('recorder-budget').textContent.includes('1,200'));
  assert(nodes.get('recorder-loss').textContent.includes('3 estimated missed samples'));
  assert(nodes.get('opportunity-status').textContent.includes('deficit 18'));
  assert.equal(nodes.get('inference-status').textContent, 'Inference OFF');
  readingsCleared();
  wall += 6000; mono += 6000; test.refreshClocks();
  assert(nodes.get('recorder-status').textContent.includes('status stale'));
  assert(nodes.get('recorder-stop').textContent.includes('Last received recorder'));
} else if (input.scenario === 'reference-select') {
  test.loadReference();
  const topics = nodes.get('reference-topics').childNodes, articles = nodes.get('reference-sections').childNodes;
  assert.equal(topics.length, 8); assert.equal(articles.filter(x => !x.hidden).length, 1);
  topics[2].listeners.click();
  assert.equal(topics[2].getAttribute('aria-current'), 'true'); assert(!articles[2].hidden);
  const search = nodes.get('reference-search'); search.value = '54.116559'; search.listeners.input();
  assert.equal(topics.filter(x => !x.hidden).length, 1); assert(!articles[2].hidden);
  search.value = 'not_a_topic'; search.listeners.input(); assert(!nodes.get('reference-empty').hidden);
  assert.equal(articles.filter(x => !x.hidden).length, 0);
  search.value = ''; search.listeners.input(); assert.equal(topics.filter(x => !x.hidden).length, 8);
} else if (input.scenario === 'phase-independent') {
  assert(visible()); assert.equal(nodes.get('game-phase').textContent, '-');
  assert.equal(nodes.get('board-cards').childNodes.length, 5);
  assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
} else if (input.scenario === 'board-transitions') {
  const cards = ['Qd', 'Ah', '2d', 'Td', '7c'].map(card => ({ rank: card[0], suit: card[1] }));
  for (const [step, count] of [3, 4, 5, 0, null].entries()) {
    const next = newer(step + 2, input.snapshot.event_seq + step + 1);
    const partial = next.partial_observation;
    Object.assign(partial, { role: 'uncertain', hero_seated: null, game_phase: null,
      board_count: count, board_slots: cards.map((card, i) => count !== null && i < count ? card : null) });
    const statuses = partial.field_statuses;
    for (const field of ['role', 'hero_seated', 'game_phase']) statuses[field] = { status: 'unavailable', reason: 'below-floor' };
    statuses.board_count = count === null ? { status: 'unavailable', reason: 'below-floor' } : { status: 'accepted' };
    for (let i = 1; i <= 5; i += 1) statuses[`board_slots.${i}`] = count !== null && i <= count ?
      { status: 'accepted' } : { status: 'unavailable', reason: 'below-floor' };
    accept(next); assert(visible()); assert.equal(nodes.get('source-role').textContent, 'Uncertain');
    assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
    if (count === 0) assert.equal(nodes.get('board-reason').textContent, 'No community cards');
    else if (count === null) {
      assert.equal(nodes.get('board-cards').childNodes.length, 5);
      assert(nodes.get('board-cards').childNodes.every(card => card.classList.contains('unknown-card')));
      assert(nodes.get('board-reason').textContent.includes('Below floor'));
    } else {
      assert.equal(nodes.get('board-cards').childNodes.length, 5);
      assert(nodes.get('board-cards').childNodes.slice(0, count).every(card => !card.classList.contains('unknown-card')));
      assert(nodes.get('board-cards').childNodes.slice(count).every(card => card.classList.contains('unknown-card')));
    }
    assert.equal(nodes.get('action-move').textContent, 'Reading uncertain');
    assert.equal(nodes.get('action-amount').textContent, '-');
    assert(nodes.get('action-amount-wrap').hidden);
  }
} else if (input.scenario === 'hero-independent') {
  assert.equal(nodes.get('source-role').textContent, 'Uncertain');
  assert.equal(nodes.get('amount-stack').textContent, '21.45');
  assert.equal(nodes.get('amount-call').textContent, '-');
  assert(!nodes.get('hero-stack-reading').hidden);
  assert.equal(nodes.get('hero-label').textContent, 'Hero / seat 2');
} else if (input.scenario === 'manual-blocked') {
  readingsCleared();
} else if (input.scenario === 'manual-empty') {
  assert(!visible()); assert(nodes.get('monitor-empty').textContent.includes('No admissible result'));
  assert(nodes.get('field-diagnostics').textContent.includes('Below floor'));
} else if (input.scenario === 'manual-partial') {
  assert(visible()); assert.equal(nodes.get('amount-pot').textContent, '123.45');
  assert.equal(nodes.get('game-phase').textContent, '-');
  assert.equal(nodes.get('board-cards').childNodes.length, 5);
  assert(nodes.get('board-cards').childNodes[0].getAttribute('aria-label').includes('Ace'));
  assert(nodes.get('board-cards').childNodes[1].getAttribute('aria-label').includes('unknown'));
  assert(nodes.get('field-diagnostics').textContent.includes('Below floor'));
  assert(nodes.get('seat-readings').textContent.includes('Occluded'));
  assert.equal(nodes.get('hero-label').textContent, 'Hero');
  assert.equal(nodes.get('hero-cards').textContent, '-');
  assert.equal(nodes.get('amount-stack').textContent, '-');
  assert.equal(nodes.get('source-role').textContent, 'Uncertain');
  assert.equal(nodes.get('acting-seat').textContent, '-');
  assert(nodes.get('controls-reading').hidden); assert(nodes.get('metrics-readings').hidden);
  for (const seat of nodes.get('seat-readings').childNodes) {
    assert(seat.textContent.includes('Untrained'));
    assert(!/BTN|SB|BB|Acting|Badge/.test(seat.textContent));
  }
  assert.equal(nodes.get('action-amount').textContent, '-');
  assert(![...nodes.values()].some(item => item.textContent.includes('$') || item.textContent.includes('PRIVATE')));
} else if (input.scenario === 'manual-invalidation') {
  assert(visible());
  const next = newer(2, input.snapshot.event_seq + 1);
  for (const [key, fields] of Object.entries(input.update)) Object.assign(next[key], fields);
  accept(next); readingsCleared();
  if (input.stopReason) assert(nodes.get('recorder-stop').textContent.includes(input.stopReason));
  // A newer inference ticket cannot override a terminal receipt or engine failure.
  next.event_seq += 1; next.partial_observation.generation += 1; accept(next); readingsCleared();
} else if (input.scenario === 'manual-receipt-expiry') {
  assert(visible()); wall += 501; mono += 501; test.refreshClocks(); readingsCleared();
  assert(nodes.get('recorder-status').textContent.includes('status stale'));
  assert(nodes.get('inference-status').textContent.includes('status stale'));
} else if (input.scenario === 'manual-lease-expiry') {
  assert(visible()); wall += 1001; mono += 1001; test.refreshClocks(); readingsCleared();
  assert(nodes.get('inference-status').textContent.includes('no admissible result'));
  assert(nodes.get('field-diagnostics').textContent.includes('Stale'));
} else if (input.scenario === 'manual-malformed') {
  assert(visible());
  for (const receipt of input.invalid) {
    const raw = structuredClone(input.snapshot); raw.capture_session = receipt;
    assert.equal(value(raw), null, JSON.stringify(receipt));
  }
} else if (input.scenario === 'manual-disconnect') {
  assert(visible()); test.suspend(); readingsCleared();
  assert.equal(nodes.get('source-status').textContent, 'Disconnected');
  assert.equal(nodes.get('inference-status').textContent, 'Inference status unavailable');
  assert.equal(nodes.get('model-status').textContent, 'Disconnected');
  assert(nodes.get('recorder-stop').textContent.includes('Last received recorder'));
} else if (input.scenario === 'manual-budget-timeout') {
  assert(visible());
  wall += input.clock === 'backward' ? -100 : 11;
  mono += input.clock === 'forward' ? 0 : 11;
  test.refreshClocks(); readingsCleared();
  assert(nodes.get('inference-status').textContent.includes('budget closed'));
  const forged = newer(2, input.snapshot.event_seq + 1);
  Object.assign(forged.capture_session, { remaining_ms: 600000, elapsed_ms: 0, max_duration_ms: 600000,
    updated_at_unix_ms: wall });
  forged.capture.last_heartbeat_unix_ms = wall;
  accept(forged); readingsCleared();
} else if (input.scenario === 'manual-budget-no-renewal') {
  assert(visible()); wall += 5; mono += 5;
  const forged = newer(2, input.snapshot.event_seq + 1);
  Object.assign(forged.capture_session, { remaining_ms: 600000, elapsed_ms: 0, max_duration_ms: 600000,
    updated_at_unix_ms: wall });
  forged.capture.last_heartbeat_unix_ms = wall;
  accept(forged); assert(visible());
  if (input.reconnect) { test.suspend(); test.resume(); forged.event_seq += 1; forged.partial_observation.generation += 1; accept(forged); }
  wall += 6; mono += 6; test.refreshClocks(); readingsCleared();
} else if (input.scenario === 'manual-budget-shorten') {
  assert(visible());
  const next = newer(2, input.snapshot.event_seq + 1);
  if (input.roundTrip) test.acceptSnapshot(value(next), input.roundTrip);
  else { Object.assign(next.capture_session, { remaining_ms: 10, elapsed_ms: 990 }); accept(next); }
  assert(visible()); wall += input.advance; mono += input.advance; test.refreshClocks(); readingsCleared();
} else if (input.scenario === 'manual-frame-budget') {
  assert(visible());
  const next = newer(2, input.snapshot.event_seq + 1);
  Object.assign(next.capture_session, { max_frames: 1200, recorded_frames: 3 });
  accept(next); readingsCleared();
  Object.assign(next.capture_session, { recorded_frames: 1 });
  next.event_seq += 1; next.partial_observation.generation += 1; accept(next); readingsCleared();
} else if (input.scenario === 'manual-session-replaced') {
  assert(visible());
  const next = newer(2, input.snapshot.event_seq + 1);
  next.capture_session.session_id = 'manual-session-b';
  accept(next); readingsCleared();
  next.event_seq += 1; next.partial_observation.generation += 1;
  accept(next); assert(visible());
  next.capture_session.session_id = input.snapshot.capture_session.session_id;
  next.event_seq += 1; next.partial_observation.generation += 1; accept(next); readingsCleared();
} else if (input.scenario === 'manual-session-closed') {
  assert(visible());
  const next = newer(2, input.snapshot.event_seq + 1);
  if (input.absent) delete next.capture_session;
  else next.capture_session.status = 'stopped';
  accept(next); readingsCleared();
  next.capture_session = structuredClone(input.snapshot.capture_session);
  next.event_seq += 1; next.partial_observation.generation += 1; accept(next); readingsCleared();
  next.session_id = 'replacement-feed'; next.event_seq += 1; accept(next); readingsCleared();
  next.event_seq += 1; next.partial_observation.generation += 1; accept(next); readingsCleared();
} else if (input.scenario === 'automatic-active') {
  assert(visible()); assert.equal(nodes.get('source-status').textContent, 'Observing active table');
  assert.equal(nodes.get('source-role').textContent, 'Uncertain');
  assert.equal(nodes.get('hero-label').textContent, 'Hero');
  assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
  assert.equal(nodes.get('amount-stack').textContent, '-');
  assert.equal(nodes.get('acting-seat').textContent, '-');
  assert(nodes.get('controls-reading').hidden); assert(nodes.get('metrics-readings').hidden);
  assert.equal(nodes.get('seat-readings').childNodes.length, 6);
  assert(nodes.get('seat-readings').childNodes.every(seat => seat.textContent.includes('Untrained')));
  assert(!nodes.get('seat-readings').textContent.includes('Acting'));
} else if (input.scenario === 'automatic-preactivity') {
  assert(visible()); assert.equal(nodes.get('source-status').textContent, 'Source capturing / verifying table activity');
  assert(nodes.get('recorder-status').textContent.includes('capturing / activity verifying'));
  assert(nodes.get('inference-status').textContent.includes('partial result / activity verifying'));
  assert.equal(nodes.get('source-role').textContent, 'Uncertain'); assert.equal(nodes.get('hero-label').textContent, 'Hero');
  assert.equal(nodes.get('hero-cards').textContent, '-'); assert.equal(nodes.get('amount-stack').textContent, '-');
  assert.equal(nodes.get('acting-seat').textContent, '-'); assert.equal(nodes.get('amount-call').textContent, '-');
  assert(nodes.get('controls-reading').hidden); assert(nodes.get('metrics-readings').hidden);
  assert(nodes.get('history-panel').hidden); assert.equal(nodes.get('history-events').childNodes.length, 0);
  assert.equal(nodes.get('history-folds').textContent, '-'); assert.equal(nodes.get('action-amount').textContent, '-');
  assert.equal(nodes.get('seat-readings').childNodes.length, 6);
  assert(!nodes.get('seat-readings').textContent.includes('Acting'));
} else if (input.scenario === 'saved-qualified-history') {
  readingsCleared(); assert(!nodes.get('history-panel').hidden);
  assert.equal(nodes.get('history-folds').textContent, '2');
  assert.equal(nodes.get('history-events').childNodes.length, 1);
} else if (input.scenario === 'automatic-transition') {
  readingsCleared(); assert.equal(nodes.get('source-status').textContent, 'Verifying table activity');
  const next = newer(2, input.snapshot.event_seq + 1);
  Object.assign(next.capture, { state: 'active', fresh_capture: true });
  accept(next); assert(visible());
  assert.equal(nodes.get('source-status').textContent, 'Source capturing / verifying table activity');
  next.event_seq += 1; next.capture_session.activity_state = 'active'; accept(next); assert(visible());
  assert.equal(nodes.get('source-status').textContent, 'Observing active table');
  assert.equal(nodes.get('source-role').textContent, 'Uncertain');
  next.event_seq += 1; next.capture_session.activity_state = 'verifying'; accept(next); assert(visible());
  next.event_seq += 1; next.capture_session.activity_state = 'active'; accept(next); assert(visible());
  next.event_seq += 1; next.partial_observation.generation += 1; accept(next); assert(visible());
  next.event_seq += 1; next.capture_session.status = 'stopped';
  next.capture_session.activity_state = 'idle'; next.capture_session.stop_reason = 'table-activity-unconfirmed';
  next.automatic_startup = { enabled: true, status: 'stopped', stop_reason: null };
  accept(next); readingsCleared();
  assert(nodes.get('recorder-stop').textContent.includes('table-activity-unconfirmed'));
  assert(nodes.get('monitor-empty').textContent.includes('Table activity unconfirmed'));
  assert(nodes.get('recorder-budget').textContent.includes(`${next.capture_session.recorded_frames} /`));
  assert.notEqual(nodes.get('recorder-loss').textContent, 'No current session receipt');
} else if (input.scenario === 'automatic-startup-terminal') {
  assert(visible());
  const next = newer(2, input.snapshot.event_seq + 1);
  next.automatic_startup = { enabled: true, status: 'failed', stop_reason: 'automatic-startup-failed' };
  accept(next); readingsCleared();
  assert(nodes.get('recorder-stop').textContent.includes('automatic-startup-failed'));
  next.automatic_startup.status = 'active'; next.automatic_startup.stop_reason = null;
  next.event_seq += 1; next.partial_observation.generation += 1; accept(next); readingsCleared();
} else if (input.scenario === 'automatic-malformed') {
  for (const changes of input.invalid) {
    const raw = structuredClone(input.snapshot);
    Object.assign(raw, changes);
    assert.equal(value(raw), null, JSON.stringify(changes));
  }
} else if (input.scenario === 'legacy') {
  assert(visible()); assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
} else if (input.scenario === 'bounded-policy-no-upgrade') {
  assert(visible()); const next = newer(2, input.snapshot.event_seq + 1);
  next.capture_session = input.sustained; accept(next); readingsCleared();
  accept(newer(3, input.snapshot.event_seq + 2)); readingsCleared();
}
if (input.scenario.startsWith('sustained-')) {
  const seq = input.snapshot.event_seq;
  const pulse = raw => { raw.capture.last_heartbeat_unix_ms = wall; raw.capture_session.updated_at_unix_ms = wall; return raw; };
  const tick = ms => { wall += ms; mono += ms; };
  const observing = () => {
    assert.equal(nodes.get('source-status').textContent, 'Observing same table');
    assert(nodes.get('monitor-lifecycle').hidden); assert(nodes.get('metrics-readings').hidden);
    assert(nodes.get('controls-reading').hidden); assert.equal(nodes.get('action-amount').textContent, '-');
  };
  const ended = reason => {
    observing(); assert(nodes.get('recorder-status').textContent.includes('Evidence recording ended; observation continues'));
    assert(nodes.get('recorder-status').textContent.includes(reason));
    assert(!nodes.get('recorder-stop').textContent.includes('Stops at the first budget limit'));
    assert(nodes.get('recorder-budget').textContent.includes('1,073,741,824 bytes'));
  };
  const recovery = reason => {
    readingsCleared(); assert(!nodes.get('monitor-lifecycle').hidden);
    assert(nodes.get('monitor-stop').textContent.includes(reason));
    // The minimal DOM harness does not parse static text; the visible main-view paragraph must contain it.
    assert(/<p id="monitor-recovery"[^>]*>[^<]*never starts capture or inference\.<\/p>/.test(html));
    assert(!nodes.get('monitor-launch').hidden);
    assert.equal(nodes.get('monitor-launch').textContent, 'scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ContinuousObservation');
    assert(!nodes.get('recorder-status').textContent.includes('observation continues'));
  };
  if (input.scenario === 'sustained-long') {
    observing(); assert(visible()); assert(nodes.get('recorder-status').textContent.includes('Evidence recording active'));
    let evidence = structuredClone(input.snapshot.capture_session.evidence), closed;
    for (let step = 1; step <= 1220; step += 1) {
      tick(500); const next = pulse(newer(step + 1, seq + step));
      next.capture.frames += step; next.capture_session.elapsed_ms += step * 500;
      if (evidence.status === 'active') {
        evidence.elapsed_ms = Math.min(evidence.max_duration_ms, next.capture_session.elapsed_ms);
        evidence.recorded_frames = 2 + Math.floor(step / 2); evidence.recorded_bytes = evidence.recorded_frames * 100;
        if (evidence.elapsed_ms === evidence.max_duration_ms) {
          evidence.status = 'ended'; evidence.stop_reason = 'duration-limit'; closed = structuredClone(evidence);
        }
      }
      next.capture_session.evidence = structuredClone(evidence);
      next.capture_session.recorded_frames = evidence.recorded_frames; next.capture_session.recorded_bytes = evidence.recorded_bytes;
      accept(next); observing(); assert(visible()); assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
      assert.equal(next.capture_session.session_id, input.snapshot.capture_session.session_id);
      if (closed) assert.deepEqual(next.capture_session.evidence, closed);
      if (step === 1220) {
        assert(next.capture_session.elapsed_ms > 600000); assert(next.capture.frames > 1200);
        assert(next.capture_session.recorded_frames < 1200); ended('duration-limit');
        assert.equal(nodes.get('capture-freshness').textContent, 'Capture current');
        assert(nodes.get('diagnostic-timing').textContent.includes('Capture 0 ms / reading 500 ms / observation 10:11'));
      }
    }
  } else if (input.scenario === 'sustained-ended') {
    assert(visible()); ended(input.snapshot.capture_session.evidence.stop_reason);
    tick(600001); const next = pulse(newer(2, seq + 1)); next.capture_session.elapsed_ms += 600001;
    accept(next); assert(visible()); ended(next.capture_session.evidence.stop_reason);
    assert.equal(next.capture_session.recorded_frames, input.snapshot.capture_session.recorded_frames);
    assert.equal(next.capture_session.recorded_bytes, input.snapshot.capture_session.recorded_bytes);
  } else if (input.scenario === 'sustained-verifying') {
    observing(); assert(visible()); assert.equal(nodes.get('source-role').textContent, 'Uncertain');
    assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
    assert(nodes.get('seat-readings').childNodes[0].textContent.includes('1.00 chips'));
    assert.equal(nodes.get('hero-cards').textContent, '-'); assert.equal(nodes.get('amount-stack').textContent, '-');
    assert.equal(nodes.get('acting-seat').textContent, '-'); assert(!nodes.get('seat-readings').textContent.includes('Acting'));
    assert(nodes.get('history-panel').hidden); assert.equal(nodes.get('history-events').childNodes.length, 0);
    assert(nodes.get('inference-status').textContent.includes('partial result / activity verifying'));
    const next = pulse(newer(2, seq + 1)); next.capture_session.activity_state = 'active'; accept(next);
    assert(!nodes.get('history-panel').hidden); assert.equal(nodes.get('history-folds').textContent, '2');
  } else if (input.scenario === 'sustained-lease') {
    observing(); assert(visible());
    for (let step = 1; step <= 5; step += 1) {
      tick(1000); const next = pulse(structuredClone(input.snapshot)); next.event_seq += step;
      accept(next); observing();
    }
    assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read');
    assert(nodes.get('pot-reason').textContent.includes('5s+ source age / not current'));
    assert(nodes.get('field-diagnostics').textContent.includes('5,000 ms source age / not current'));
    assert.equal(nodes.get('source-freshness').textContent, 'Last-read amounts only / not current');
    const forged = pulse(newer(1, seq + 6)); accept(forged);
    assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read');
    accept(pulse(newer(2, seq + 7))); assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
  } else if (input.scenario === 'sustained-capture-stale') {
    assert(visible()); tick(2501); const next = pulse(newer(2, seq + 1));
    next.capture.last_heartbeat_unix_ms = input.snapshot.capture.last_heartbeat_unix_ms;
    accept(next); readingsCleared();
    assert(!nodes.get('recorder-status').textContent.includes('observation continues'));
    assert(nodes.get('capture-freshness').textContent.includes('not current'));
  } else if (input.scenario === 'sustained-receipt-stale') {
    assert(visible()); tick(input.advance); test.refreshClocks(); readingsCleared();
    assert.equal(nodes.get('source-status').textContent, 'Session status stale');
  } else if (input.scenario === 'sustained-heartbeat-no-renewal') {
    assert(visible()); tick(2500); const next = newer(2, seq + 1);
    // A fresh acquisition does not renew an unchanged receipt heartbeat.
    next.capture_session.updated_at_unix_ms = input.snapshot.capture_session.updated_at_unix_ms;
    accept(next); assert(visible()); wall -= 100; mono += 501; test.refreshClocks(); readingsCleared();
    assert.equal(nodes.get('source-status').textContent, 'Session status stale');
  } else if (input.scenario === 'sustained-terminal') {
    assert(visible()); const next = pulse(newer(2, seq + 1));
    Object.assign(next.capture_session, { status: input.status, activity_state: 'idle', stop_reason: input.reason });
    accept(next); recovery(input.reason);
    next.capture_session = structuredClone(input.snapshot.capture_session);
    next.event_seq += 1; next.partial_observation.generation += 1; accept(pulse(next)); readingsCleared();
    assert.notEqual(nodes.get('source-status').textContent, 'Observing same table');
    assert(nodes.get('monitor-stop').textContent.includes(input.reason));
    next.session_id = 'replacement-feed'; next.event_seq += 1; accept(pulse(next)); readingsCleared();
    next.event_seq += 1; next.partial_observation.generation += 1; accept(pulse(next)); readingsCleared();
  } else if (input.scenario === 'sustained-startup-terminal') {
    assert(visible()); const next = pulse(newer(2, seq + 1));
    next.automatic_startup = { enabled: true, status: 'failed', stop_reason: 'automatic-startup-failed' };
    accept(next); recovery('automatic-startup-failed');
    next.automatic_startup.status = 'active'; next.automatic_startup.stop_reason = null;
    next.event_seq += 1; next.partial_observation.generation += 1; accept(pulse(next)); readingsCleared();
  } else if (input.scenario === 'sustained-evidence-no-renewal') {
    assert(visible()); ended(input.snapshot.capture_session.evidence.stop_reason);
    const next = pulse(newer(2, seq + 1)); Object.assign(next.capture_session.evidence, input.rewrite);
    next.capture_session.recorded_frames = next.capture_session.evidence.recorded_frames;
    next.capture_session.recorded_bytes = next.capture_session.evidence.recorded_bytes;
    accept(next); readingsCleared(); assert.notEqual(nodes.get('source-status').textContent, 'Observing same table');
    accept(pulse(newer(3, seq + 2))); readingsCleared();
  } else if (input.scenario === 'sustained-source-no-rearm') {
    assert(visible()); const next = pulse(newer(2, seq + 1));
    for (const [key, fields] of Object.entries(input.update || {})) Object.assign(next[key], fields);
    if (input.message) next.message = input.message;
    if (input.feedSession) next.session_id = 'replacement-feed';
    accept(next); readingsCleared();
    const restored = pulse(newer(3, seq + 2));
    if (input.feedSession) restored.session_id = next.session_id;
    accept(restored); readingsCleared();
    assert.notEqual(nodes.get('source-status').textContent, 'Observing same table');
  } else if (input.scenario === 'sustained-resize') {
    const stackValue = seat => nodes.get('seat-readings').childNodes[seat - 1].childNodes[1].childNodes[0].childNodes[1];
    const budget = nodes.get('recorder-budget').textContent;
    const original = structuredClone(input.snapshot.capture_session);
    const scope = { epoch: input.snapshot.capture.epoch + 1, width: input.snapshot.capture.width + 20,
      height: input.snapshot.capture.height + 10, state: 'active', fresh_capture: true };
    const scoped = (gen, event) => {
      const raw = pulse(newer(gen, event)); Object.assign(raw.capture, scope);
      raw.capture_session.elapsed_ms = original.elapsed_ms + mono;
      return raw;
    };
    const fresh = (gen, event) => {
      const raw = scoped(gen, event), obs = raw.partial_observation;
      obs.epoch = scope.epoch; obs.captured_at_unix_ms = wall - 25;
      obs.game_phase = null; obs.board_count = null; obs.board_slots = [null, null, null, null, null];
      obs.pot_size = 7777; obs.pot_size_text = null;
      for (const seat of obs.seats) { seat.displayed_stack = seat.seat === 3 ? 30300 : null; delete seat.displayed_stack_text; }
      obs.field_statuses = { pot_size: { status: 'accepted', reason: null }, 'seats.3.displayed_stack': { status: 'accepted', reason: null } };
      return raw;
    };
    const current = () => {
      observing(); assert(visible()); assert.equal(nodes.get('amount-pot').textContent, '77.77 chips');
      assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
      assert.equal(stackValue(3).textContent, '303.00 chips'); assert.equal(stackValue(3).dataset.reading, 'current');
      for (const seat of [1, 2, 4, 5, 6]) assert.equal(stackValue(seat).dataset.reading, 'unknown');
      assert.equal(nodes.get('recorder-budget').textContent, budget);
    };
    assert(visible()); tick(1001); test.refreshClocks(); assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read');
    const boundary = scoped(2, seq + 1);
    boundary.message = input.wait ? 'capture-not-fresh' : input.marker ? 'capture-identity-or-epoch-changed' : 'Partial reading';
    if (input.wait) Object.assign(boundary.capture, { epoch: null, width: null, height: null, state: 'verifying', fresh_capture: false });
    accept(boundary); readingsCleared(); assert(nodes.get('monitor-lifecycle').hidden);
    assert.equal(nodes.get('recorder-budget').textContent, budget);
    tick(100); const old = scoped(2, seq + 2); old.partial_observation.pot_size = 99999999;
    accept(old); readingsCleared(); assert(nodes.get('monitor-lifecycle').hidden);
    tick(100); const admitted = fresh(3, seq + 3); accept(admitted); current();
    assert.equal(admitted.capture_session.session_id, original.session_id);
    assert(admitted.capture_session.elapsed_ms > original.elapsed_ms);
    assert.deepEqual(admitted.capture_session.evidence, original.evidence);
    assert.equal(admitted.capture_session.recorded_frames, original.recorded_frames);
    assert.equal(admitted.capture_session.recorded_bytes, original.recorded_bytes);
    const replay = scoped(99, seq + 4); accept(replay); readingsCleared();
    tick(100); accept(fresh(4, seq + 5)); current();
    tick(1001); test.refreshClocks(); assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read');
    assert.equal(stackValue(3).dataset.reading, 'last-read');
    for (const seat of [1, 2, 4, 5, 6]) assert.equal(stackValue(seat).dataset.reading, 'unknown');
    assert.equal(nodes.get('recorder-budget').textContent, budget);
    if (input.rewrite) {
      const forged = fresh(5, seq + 6); Object.assign(forged.capture_session.evidence, input.rewrite);
      forged.capture_session.recorded_frames = forged.capture_session.evidence.recorded_frames;
      forged.capture_session.recorded_bytes = forged.capture_session.evidence.recorded_bytes;
      accept(forged); readingsCleared(); assert(!nodes.get('monitor-lifecycle').hidden);
      accept(fresh(6, seq + 7)); readingsCleared();
    }
  } else if (input.scenario === 'sustained-initial-health-wait') {
    readingsCleared(); assert(nodes.get('monitor-lifecycle').hidden);
    tick(100); const fresh = pulse(newer(2, seq + 1)); Object.assign(fresh.capture, input.scope);
    accept(fresh); assert(visible()); observing();
    assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
  } else if (input.scenario === 'sustained-first-live-claim') {
    const original = input.snapshot.capture_session;
    const budget = nodes.get('recorder-budget').textContent;
    const native = (event, gen = null) => {
      const raw = pulse(structuredClone(input.live)); raw.event_seq = event;
      raw.capture_session.elapsed_ms = original.elapsed_ms + Math.floor(mono / 16) * 16;
      if (gen === null) raw.partial_observation = null;
      else {
        const obs = raw.partial_observation;
        obs.generation = gen; obs.captured_at_unix_ms = wall - 25;
        obs.expires_at_unix_ms = wall + 1000; obs.remaining_ms = 1000;
        obs.pot_size = 7777; obs.pot_size_text = null;
        for (const seat of obs.seats) { seat.displayed_stack = null; delete seat.displayed_stack_text; }
        obs.field_statuses = { pot_size: { status: 'accepted', reason: null } };
      }
      return raw;
    };
    readingsCleared();
    if (!input.terminal) assert(nodes.get('monitor-lifecycle').hidden);
    if (input.preclaim) {
      tick(100); const warm = native(0, 1); warm.session_id = 'sdk-warm-feed';
      warm.capture.fresh_capture = false; accept(warm); readingsCleared();
      assert(nodes.get('monitor-lifecycle').hidden);
      tick(1); const warmPoll = native(1, 2); warmPoll.session_id = warm.session_id;
      warmPoll.capture.fresh_capture = false; accept(warmPoll); readingsCleared();
    }
    tick(input.rollback ? 2500 : input.stale ? 3001 : 100);
    if (input.rollback) { wall -= 100; mono += 501; }
    const claim = native(0);
    if (input.stale) claim.capture_session.updated_at_unix_ms = original.updated_at_unix_ms;
    if (input.service) claim.server.instance_id = input.service;
    if (input.rewrite) Object.assign(claim.capture_session.evidence, input.rewrite);
    accept(claim); readingsCleared();
    const blocked = input.terminal || input.stale || input.service || input.rewrite;
    if (blocked) {
      tick(100); const fresh = native(1, 2);
      if (input.stale) fresh.capture_session.updated_at_unix_ms = original.updated_at_unix_ms;
      accept(fresh); readingsCleared();
      assert.notEqual(nodes.get('source-status').textContent, 'Observing same table');
      if (input.stale) assert.equal(nodes.get('source-status').textContent, 'Session status stale');
      else assert(!nodes.get('monitor-lifecycle').hidden);
    } else {
      observing(); assert.equal(nodes.get('recorder-budget').textContent, budget);
      // The first stream claim has health only. A later fresh ticket, not boot data, establishes numeric admission.
      tick(100); const first = native(1, 2); accept(first); observing(); assert(visible());
      assert.equal(nodes.get('amount-pot').textContent, '77.77 chips');
      assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
      assert(!nodes.get('seat-readings').textContent.includes('Last read'));
      assert.deepEqual(first.capture_session.evidence, original.evidence);
      assert.equal(first.capture_session.recorded_frames, original.recorded_frames);
      assert.equal(first.capture_session.recorded_bytes, original.recorded_bytes);
      // A coarsely clocked native elapsed value may repeat, but must never be wall-age interpolated or regress.
      for (let step = 1; step <= (input.long ? 390 : 3); step += 1) {
        tick(input.long ? 500 : 1); const fresh = native(step + 1, step + 2); accept(fresh);
        observing(); assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
        assert.equal(fresh.session_id, first.session_id); assert.equal(fresh.server.instance_id, first.server.instance_id);
        assert.equal(fresh.capture_session.session_id, original.session_id);
        assert.deepEqual(fresh.capture_session.evidence, original.evidence);
        if (input.long && step === 390) assert(fresh.capture_session.elapsed_ms - original.elapsed_ms > 180000);
      }
      if (input.later) {
        const replaced = native(392, 400);
        if (input.later === 'feed' || input.later === 'idle-feed') replaced.session_id = 'replacement-native-feed';
        if (input.later === 'idle-feed') {
          replaced.source = 'idle'; replaced.capture.fresh_capture = false;
          Object.assign(replaced.capture, { epoch: null, width: null, height: null });
        }
        if (input.later === 'service') replaced.server.instance_id = 'replacement-service';
        if (input.later === 'owner') replaced.capture_session.session_id = 'replacement-owner';
        accept(replaced); readingsCleared();
        const replay = native(393, 401);
        if (input.later === 'feed' || input.later === 'idle-feed') replay.session_id = replaced.session_id;
        accept(replay); readingsCleared();
      } else {
        tick(1001); test.refreshClocks();
        assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read');
        assert(nodes.get('pot-reason').textContent.includes('not current'));
      }
    }
  } else if (input.scenario === 'sustained-malformed') {
    assert(visible());
    for (const receipt of input.invalid) {
      const raw = structuredClone(input.snapshot); raw.capture_session = receipt;
      assert.equal(value(raw), null, JSON.stringify(receipt));
    }
    test.suspend(); readingsCleared();
  } else if (input.scenario === 'sustained-hidden') {
    assert(visible()); document.hidden = true; test.suspend(); readingsCleared();
    document.hidden = false; test.resume(); accept(pulse(newer(1, seq + 1))); readingsCleared();
    accept(pulse(newer(2, seq + 2))); assert(visible()); observing();
  } else if (input.scenario === 'sustained-policy-no-upgrade') {
    assert(visible()); const next = pulse(newer(2, seq + 1)); next.capture_session = input.bounded;
    accept(next); readingsCleared();
    accept(pulse(newer(3, seq + 2))); readingsCleared();
  }
}
if (input.scenario.startsWith('retained-')) {
  const stack = seat => nodes.get('seat-readings').childNodes.find(row => row.dataset.seat === String(seat)).childNodes[1].childNodes[0];
  const stackValue = seat => stack(seat).childNodes[1];
  const ageText = age => (age < 5000 ? 'under 5s' : age < 60000 ? `${Math.floor(age / 5000) * 5}s+` : `${Math.floor(age / 60000)}m+`) + ' source age';
  const tick = ms => { wall += ms; mono += ms; };
  const pulse = raw => { raw.capture.last_heartbeat_unix_ms = wall; raw.capture_session.updated_at_unix_ms = wall; return raw; };
  const absent = seq => { const raw = pulse(structuredClone(input.snapshot)); raw.event_seq = seq;
    raw.partial_observation = null; raw.observation = null; return raw; };
  const field = (gen, seq, key, amount) => {
    const raw = pulse(newer(gen, seq)), obs = raw.partial_observation;
    obs.game_phase = null; obs.board_count = null; obs.board_slots = [null, null, null, null, null];
    obs.pot_size = null; delete obs.pot_size_text;
    for (const seat of obs.seats) { seat.displayed_stack = null; delete seat.displayed_stack_text; }
    obs.field_statuses = {};
    if (key === 'pot_size') obs.pot_size = amount;
    else if (key) obs.seats[Number(key.split('.')[1]) - 1].displayed_stack = amount;
    if (key) obs.field_statuses[key] = { status: 'accepted', reason: null };
    return raw;
  };
  const nonnumericCleared = () => {
    assert(nodes.get('suggested-action').hidden); assert.equal(nodes.get('source-role').textContent, 'Role unknown');
    for (const id of ['amount-stack', 'amount-call', 'amount-min', 'amount-max', 'acting-seat', 'game-phase', 'hero-cards']) assert.equal(nodes.get(id).textContent, '-', id);
    assert(nodes.get('board-cards').childNodes.every(card => card.classList.contains('unknown-card')));
    assert(nodes.get('controls-reading').hidden); assert(nodes.get('metrics-readings').hidden);
    assert(nodes.get('wagers-reading').hidden); assert(nodes.get('actor-reading').hidden);
    assert(nodes.get('history-panel').hidden); assert.equal(nodes.get('history-events').childNodes.length, 0);
    assert(!/BTN|Badge|Acting|Occupied|Open/.test(nodes.get('seat-readings').textContent));
  };
  const retainedOnly = (age, reason = 'Awaiting recheck') => {
    assert(visible()); assert(nodes.get('monitor-empty').hidden);
    assert(!nodes.get('monitor-grid').classList.contains('no-reading'));
    assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read');
    assert(nodes.get('amount-pot').classList.contains('retained-number'));
    assert(nodes.get('pot-reason').textContent.includes(`Last read / ${reason}`));
    assert(nodes.get('pot-reason').textContent.includes(ageText(age)));
    assert(nodes.get('field-diagnostics').textContent.includes(new Intl.NumberFormat('en-US').format(age) + ' ms source age'));
    assert(nodes.get('pot-reason').textContent.includes('not current'));
    assert.equal(nodes.get('seat-readings').childNodes.length, 6);
    for (let seat = 1; seat <= 6; seat += 1) {
      assert.equal(stackValue(seat).dataset.reading, 'last-read');
      assert(stackValue(seat).classList.contains('retained-number'));
      assert(stack(seat).textContent.includes(`Last read / ${reason}`));
      assert(stack(seat).textContent.includes(ageText(age)));
      assert(stack(seat).textContent.includes('not current'));
    }
    assert.equal(nodes.get('source-freshness').textContent, 'Last-read amounts only / not current');
    if (!input.noReadingHeading) assert.equal(nodes.get('observation-title').textContent, 'Last-read amounts');
    assert(nodes.get('inference-status').textContent.includes('last-read amounts only / no current reading'));
    nonnumericCleared();
  };
  const seq = input.snapshot.event_seq;
  if (input.scenario === 'retained-independent') {
    assert.equal(nodes.get('observation-title').textContent, 'Current readings');
    assert.equal(nodes.get('amount-pot').dataset.reading, 'current'); assert.equal(nodes.get('pot-reason').textContent, '');
    tick(1001); test.refreshClocks(); retainedOnly(1501);
    assert.equal(stackValue(4).textContent, '0.00 chips');
    accept(field(2, seq + 1, 'pot_size', 7777));
    assert.equal(nodes.get('observation-title').textContent, 'Current readings');
    assert.equal(nodes.get('amount-pot').textContent, '77.77 chips'); assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
    assert.equal(nodes.get('pot-reason').textContent, ''); assert(!nodes.get('amount-pot').classList.contains('retained-number'));
    assert(stack(1).textContent.includes(ageText(1501))); assert.equal(stackValue(1).textContent, '1.00 chips');
    tick(200); accept(field(3, seq + 2, 'seats.5.displayed_stack', 50500));
    assert.equal(stackValue(5).textContent, '505.00 chips'); assert.equal(stackValue(5).dataset.reading, 'current');
    assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read'); assert(nodes.get('pot-reason').textContent.includes(ageText(700)));
    assert(stack(1).textContent.includes(ageText(1701))); assert.equal(stackValue(4).textContent, '0.00 chips');
    tick(200); accept(field(4, seq + 3, 'seats.1.displayed_stack', 0));
    assert.equal(stackValue(1).textContent, '0.00 chips'); assert.equal(stackValue(1).dataset.reading, 'current');
    assert.equal(stackValue(5).textContent, '505.00 chips'); assert.equal(stackValue(5).dataset.reading, 'last-read');
    assert(stack(5).textContent.includes(ageText(700))); assert(stack(4).textContent.includes(ageText(1901)));
    accept(absent(seq + 4));
    assert.equal(stackValue(1).textContent, '0.00 chips'); assert.equal(stackValue(1).dataset.reading, 'last-read');
    assert.equal(stackValue(2).textContent, '2.00 chips'); assert.equal(nodes.get('amount-pot').textContent, '77.77 chips');
    nonnumericCleared();
  } else if (input.scenario === 'retained-calm-clock') {
    const captureLabel = nodes.get('capture-freshness').textContent;
    const readingLabel = nodes.get('source-freshness').textContent;
    assert.equal(captureLabel, 'Capture current'); assert.equal(readingLabel, 'Reading age under 5s');
    assert(nodes.get('diagnostic-timing').textContent.includes('Capture 0 ms / reading 500 ms'));
    assert(nodes.get('reading-limit').textContent.includes('Stacks are remaining chips, not bets'));
    assert(nodes.get('reading-limit').textContent.includes('Native action inputs and complete betting history remain unavailable'));
    tick(100); test.refreshClocks();
    assert.equal(nodes.get('capture-freshness').textContent, captureLabel);
    assert.equal(nodes.get('source-freshness').textContent, readingLabel);
    assert(nodes.get('diagnostic-timing').textContent.includes('Capture 100 ms / reading 600 ms'));
    tick(901); test.refreshClocks(); retainedOnly(1501);
    assert(nodes.get('reading-limit').textContent.includes('verification expired, not that a bet occurred'));
    // Expiry is immediate, even inside the unchanged five-second display bucket.
    assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read');
    const captured = input.snapshot.partial_observation.captured_at_unix_ms;
    for (const [index, [age, label]] of [[1501, 'under 5s'], [4999, 'under 5s'], [5000, '5s+'],
      [9999, '5s+'], [10000, '10s+'], [59999, '55s+'], [60000, '1m+'], [119999, '1m+'], [120000, '2m+']].entries()) {
      tick(age - (wall - captured)); accept(absent(seq + index + 1)); retainedOnly(age);
      assert(nodes.get('pot-reason').textContent.includes(`${label} source age`));
      assert(stack(1).textContent.includes(`${label} source age`));
      assert(!/\d[\d,]* ms/.test(nodes.get('seat-readings').textContent));
      assert(!/frames|observation \d/.test(nodes.get('recorder-status').textContent));
      assert.equal(nodes.get('capture-freshness').textContent, captureLabel);
    }
    tick(2501); test.refreshClocks(); readingsCleared();
    assert(nodes.get('capture-freshness').textContent.includes('not current'));
  } else if (input.scenario === 'retained-age') {
    tick(1001); test.refreshClocks(); retainedOnly(1501);
    accept(input.snapshot); retainedOnly(1501);
    tick(200);
    const replay = pulse(structuredClone(input.snapshot)); replay.event_seq += 1;
    replay.partial_observation.expires_at_unix_ms = wall + 3000; replay.partial_observation.remaining_ms = 3000;
    replay.partial_observation.pot_size = 99999999;
    accept(replay); retainedOnly(1701); assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
    assert.equal(input.snapshot.partial_observation.expires_at_unix_ms, input.snapshot.capture.last_heartbeat_unix_ms + 1000);
    const last = absent(seq + 2); wall -= 100; mono += 200; accept(last); retainedOnly(1901);
    mono += 100; test.refreshClocks(); retainedOnly(2001);
    wall -= 10000; mono += 2000; accept(pulse(absent(seq + 3))); readingsCleared();
  } else if (input.scenario === 'retained-six') {
    let empty;
    for (let step = 1; step <= 6; step += 1) { tick(1000); empty = absent(seq + step); accept(empty); }
    retainedOnly(6500);
    assert.equal(value(empty).observation, null, 'retention must not manufacture an API observation');
    assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
    for (let seat = 1; seat <= 6; seat += 1) assert.equal(stackValue(seat).textContent, seat === 4 ? '0.00 chips' : `${seat}.00 chips`);
    test.refreshClocks(); retainedOnly(6500);
  } else if (input.scenario === 'retained-five-second-lease') {
    for (let step = 1; step <= 5; step += 1) { tick(1000); accept(pulse(structuredClone({ ...input.snapshot, event_seq: seq + step }))); }
    tick(1); accept(absent(seq + 6)); retainedOnly(5001);
    assert.equal(input.snapshot.partial_observation.remaining_ms, 5000);
    assert.equal(input.snapshot.partial_observation.expires_at_unix_ms - input.snapshot.partial_observation.captured_at_unix_ms, 5000);
  } else if (input.scenario === 'retained-changed') {
    tick(100); const changed = absent(seq + 1); changed.message = 'source-region-changed'; accept(changed); retainedOnly(600, 'Source changed');
    tick(200); accept(field(2, seq + 2, 'seats.3.displayed_stack', 3000));
    assert.equal(stackValue(3).textContent, '30.00 chips'); assert.equal(stackValue(3).dataset.reading, 'current');
    assert(nodes.get('pot-reason').textContent.includes('Source changed')); assert(nodes.get('pot-reason').textContent.includes(ageText(800)));
    accept(absent(seq + 3));
    assert(stack(3).textContent.includes('Last read / Awaiting recheck')); assert(stack(3).textContent.includes(ageText(500)));
    assert(stack(2).textContent.includes('Last read / Source changed')); assert(stack(2).textContent.includes(ageText(800)));
    nonnumericCleared();
  } else if (input.scenario === 'retained-boundary') {
    tick(1001); test.refreshClocks(); retainedOnly(1501);
    const boundary = absent(seq + 1);
    for (const [key, fields] of Object.entries(input.update)) Object.assign(boundary[key] ||= {}, fields);
    if (input.message) boundary.message = input.message;
    if (input.epoch) { boundary.partial_observation = field(2, seq + 1).partial_observation; boundary.partial_observation.epoch = 2; }
    if (input.feedSession) boundary.session_id = 'replacement-feed';
    if (input.source) boundary.source = 'idle';
    accept(boundary); readingsCleared();
    boundary.event_seq += 1; boundary.partial_observation = null; accept(boundary); readingsCleared();
  } else if (input.scenario === 'retained-transient') {
    tick(100); const lag = absent(seq + 1); lag.capture.fresh_capture = false; accept(lag); retainedOnly(600);
    assert(!nodes.get('inference-status').textContent.includes('partial result'));
    tick(2501); pulse(lag); lag.event_seq += 1; lag.capture.fresh_capture = true; accept(lag); retainedOnly(3101);
    // A recent receipt alone cannot extend the established 2500ms source-owner heartbeat bound.
    tick(2501); lag.capture_session.updated_at_unix_ms = wall; lag.event_seq += 1; accept(lag); readingsCleared();
  } else if (input.scenario === 'retained-unavailable') {
    tick(100); const lag = absent(seq + 1); lag.capture.state = 'unavailable'; lag.capture.fresh_capture = false;
    lag.message = input.reason; accept(lag); retainedOnly(600);
    tick(200); lag.event_seq += 1; pulse(lag); accept(lag); retainedOnly(800);
    tick(2501); lag.capture_session.updated_at_unix_ms = wall; lag.event_seq += 1; accept(lag); readingsCleared();
  } else if (input.scenario === 'retained-unavailable-admitted') {
    retainedOnly(500);
    assert.equal(input.snapshot.partial_observation.remaining_ms, 1000);
    tick(300); const refreshed = pulse(newer(2, seq + 1));
    Object.assign(refreshed.capture, { state: 'active', fresh_capture: true }); refreshed.message = 'Partial reading';
    accept(refreshed); assert(visible()); assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
    assert.equal(nodes.get('pot-reason').textContent, '');
    tick(1001); test.refreshClocks(); retainedOnly(1501);
  } else if (input.scenario === 'retained-epoch-fence') {
    tick(1001); const boundary = absent(seq + 1); boundary.capture.epoch = 2; accept(boundary); readingsCleared();
    const old = field(2, seq + 2, 'pot_size', 99999999); old.capture.epoch = 2;
    accept(old); readingsCleared();
    const current = field(3, seq + 3, 'pot_size', 9000); current.capture.epoch = 2; current.partial_observation.epoch = 2;
    accept(current); assert(visible()); assert.equal(nodes.get('amount-pot').textContent, '90.00 chips');
    assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
    for (let seat = 1; seat <= 6; seat += 1) assert.equal(stackValue(seat).dataset.reading, 'unknown');
    boundary.event_seq = seq + 4; accept(boundary); assert(visible());
    assert.equal(nodes.get('amount-pot').dataset.reading, 'last-read');
    for (let seat = 1; seat <= 6; seat += 1) assert.equal(stackValue(seat).dataset.reading, 'unknown');
    nonnumericCleared();
  } else if (input.scenario === 'retained-accepted-only') {
    tick(1001); test.refreshClocks();
    if (input.none) readingsCleared();
    else {
      assert(visible()); assert.equal(nodes.get('amount-pot').textContent, '-');
      assert.equal(stackValue(4).textContent, '0.00 chips'); assert.equal(stackValue(4).dataset.reading, 'last-read');
      for (const seat of [1, 2, 3, 5, 6]) assert.equal(stackValue(seat).dataset.reading, 'unknown');
      nonnumericCleared();
    }
  } else if (input.scenario === 'retained-unsafe') {
    tick(1001); test.refreshClocks(); retainedOnly(1501);
    const unsafe = absent(seq + 1); Object.assign(unsafe, input.unsafe); assert.equal(value(unsafe), null);
    test.suspend(); readingsCleared(); test.resume(); accept(absent(seq + 2)); readingsCleared();
  } else if (input.scenario === 'retained-disconnect') {
    tick(1001); test.refreshClocks(); retainedOnly(1501);
    test.suspend(); readingsCleared(); test.resume(); accept(absent(seq + 1)); readingsCleared();
  } else if (input.scenario === 'retained-empty') {
    readingsCleared(); assert(!nodes.get('seat-readings').textContent.includes('Last read'));
  }
}
if (input.scenario.startsWith('context-') || input.scenario === 'persistent-table') {
  const seats = nodes.get('seat-readings').childNodes.slice(), board = nodes.get('board-cards').childNodes.slice();
  const stack = seat => seats[seat - 1].childNodes[1].childNodes[0].childNodes[1];
  const select = seat => seats[seat - 1].childNodes[0].childNodes[0];
  const tick = ms => { wall += ms; mono += ms; };
  let sequence = input.snapshot.event_seq;
  const pulse = () => { const raw = structuredClone(input.snapshot); raw.event_seq = ++sequence;
    raw.capture.last_heartbeat_unix_ms = wall; raw.capture_session.updated_at_unix_ms = wall; return raw; };
  const fresh = () => {
    const raw = pulse(), ctx = raw.table_context;
    ctx.capture.sequence += sequence; ctx.capture.captured_at_ms += mono + sequence;
    ctx.capture.captured_at_unix_ms = wall - 10; ctx.expires_at_unix_ms = wall + 4990;
    ctx.evidence.role.capture = structuredClone(ctx.capture);
    return raw;
  };
  const persistent = () => {
    assert(!nodes.get('monitor-readings').hidden); assert.equal(nodes.get('seat-readings').childNodes.length, 6);
    assert.equal(nodes.get('board-cards').childNodes.length, 5);
    seats.forEach((seat, i) => assert.equal(nodes.get('seat-readings').childNodes[i], seat));
    board.forEach((card, i) => assert.equal(nodes.get('board-cards').childNodes[i], card));
  };
  if (input.scenario === 'persistent-table') {
    const mutations = () => seats.reduce((n, seat) => n + seat.childNodes[0].childNodes[0].childNodes[1].mutations +
      seat.childNodes[0].childNodes[1].mutations + seat.childNodes[1].childNodes[0].childNodes[1].mutations +
      seat.childNodes[1].childNodes[1].childNodes[1].mutations + seat.childNodes[2].mutations, 0) +
      board.reduce((n, card) => n + card.childNodes[0].mutations + card.childNodes[1].mutations, 0);
    const before = mutations(), count = window.monitorRenderReceipts.read().receipts.length;
    for (let i = 0; i < 5; i += 1) { tick(100); accept(input.snapshot); persistent(); }
    assert.equal(mutations(), before); assert.equal(window.monitorRenderReceipts.read().receipts.length, count);
    test.suspend(); persistent(); assert(seats.every(seat => seat.textContent.includes('Seat status pending')));
    assert(seats.every((_, i) => stack(i + 1).textContent === '-'));
  } else if (input.scenario === 'context-render') {
    persistent(); assert.equal(nodes.get('occupancy-summary').textContent, '6/6 seats occupied');
    assert.equal(nodes.get('source-role').textContent, 'Observing'); assert(!seats[3].dataset.hero.includes('true'));
    assert.equal(stack(4).textContent, '0.00 chips');
    select(1).listeners.click(); assert.equal(document.activeElement, nodes.get('player-title'));
    assert(!nodes.get('player-details').hidden); assert.equal(select(1).getAttribute('aria-expanded'), 'true');
    assert(nodes.get('player-stats').textContent.includes('12.5%')); assert(nodes.get('player-stats').textContent.includes('0%'));
    assert(nodes.get('player-stats-scope').textContent.includes('Sample size unknown / scope unknown'));
    assert(nodes.get('player-stats-status').textContent.includes('Last observed client-displayed'));
    assert(nodes.get('player-evidence').getAttribute('href').startsWith('/api/evidence/'));
    assert(!seats.some(seat => /VPIP|PFR|3-BET|C-BET/.test(seat.textContent)));
    const original = input.snapshot.table_context.seats[0].stats.capture;
    assert(nodes.get('player-stats-source').textContent.includes(new Date(original.captured_at_unix_ms).toISOString()));
    const metric = nodes.get('player-stats').childNodes[0].childNodes[1];
    const publication = metric.dataset.publishedAtUnixMs;
    tick(500); accept(pulse()); persistent(); assert.equal(metric.dataset.publishedAtUnixMs, publication);
    assert.equal(JSON.parse(metric.dataset.captureRef).sequence, original.sequence);
    assert.equal(document.activeElement, nodes.get('player-title'));
    document.listeners.keydown({ key: 'Escape', preventDefault() {} });
    assert(nodes.get('player-details').hidden); assert.equal(document.activeElement, select(1));
    select(2).listeners.click(); nodes.get('close-player-details').listeners.click();
    assert.equal(document.activeElement, select(2)); persistent();
  } else if (input.scenario === 'context-role') {
    persistent(); assert.equal(nodes.get('source-role').textContent, input.roleLabel);
    assert.equal(seats.filter(seat => seat.dataset.hero === 'true').length, input.hero === null ? 0 : 1);
    if (input.hero !== null) assert.equal(seats[input.hero - 1].dataset.hero, 'true');
    assert.equal(nodes.get('action-amount').textContent, '-'); assert(nodes.get('metrics-readings').hidden);
    assert.equal(nodes.get('history-folds').textContent, '2');
    const next = fresh(); next.table_context.role = 'observing'; next.table_context.hero_seat = null;
    next.table_context.evidence.role = { status: 'confirmed', origin: 'observer_controls', hero_seat: null,
      capture: structuredClone(next.table_context.capture) };
    accept(next); assert.equal(nodes.get('source-role').textContent, 'Observing');
    assert(seats.every(seat => seat.dataset.hero === 'false')); assert.equal(nodes.get('history-folds').textContent, '2');
  } else if (input.scenario === 'context-reject') {
    persistent(); assert(seats.every(seat => seat.textContent.includes('Seat status pending')));
    assert.equal(nodes.get('occupancy-summary').textContent, 'Occupancy uncertain');
    select(1).listeners.click(); assert(nodes.get('player-stats-status').textContent.startsWith('Unknown'));
  } else if (input.scenario === 'context-stats-reject') {
    select(1).listeners.click(); assert(nodes.get('player-stats-status').textContent.startsWith('Unknown'));
    assert(nodes.get('player-stats').childNodes.every(row => row.childNodes[1].textContent === '-'));
    assert(nodes.get('player-evidence').hidden);
  } else if (input.scenario === 'context-expiry') {
    select(1).listeners.click(); const metric = nodes.get('player-stats').childNodes[0].childNodes[1];
    const original = metric.dataset.captureRef;
    tick(4501); accept(pulse()); test.refreshClocks(); persistent();
    assert(seats.every((seat,i) => seat.textContent.includes(`Player ${i+1}`)));
    assert(seats.every(seat => seat.childNodes[0].childNodes[0].childNodes[1].dataset.reading==='last-read'));
    assert.equal(nodes.get('occupancy-summary').textContent, 'Occupancy uncertain');
    assert(nodes.get('player-stats-status').textContent.startsWith('Unknown'));
    const rewrite = pulse(); rewrite.table_context.expires_at_unix_ms = wall + 1000;
    accept(rewrite); assert(seats.every((seat,i) => seat.textContent.includes(`Player ${i+1}`)));
    assert.equal(seats[0].childNodes[0].childNodes[0].childNodes[1].dataset.reading,'last-read');
    const next = fresh(); accept(next); assert(seats[0].textContent.includes('Player 1'));
    assert.equal(metric.dataset.captureRef, original); assert(metric.dataset.reading.startsWith('last-observed/'));
  } else if (input.scenario === 'context-name-continuity') {
    select(1).listeners.click();const label=seats[0].childNodes[0].childNodes[0].childNodes[1];
    const original=label.dataset.captureRef;
    tick(10);const uncertain=fresh(); const row=uncertain.table_context.seats[0];
    row.identity=null;row.continuity='uncertain';row.status='unknown';
    accept(uncertain);persistent();assert.equal(label.textContent,'Player 1');
    assert.equal(label.dataset.reading,'last-read');assert.equal(label.dataset.captureRef,original);
    assert(label.classList.contains('retained-identity'));
    assert(nodes.get('player-title').textContent.includes('Player 1'));
    assert(nodes.get('player-stats-status').textContent.startsWith('Unknown'));
    tick(10);const absent=pulse();absent.table_context=null;accept(absent);
    assert.equal(label.textContent,'Player 1');assert.equal(label.dataset.captureRef,original);
    tick(10);const restored=fresh();accept(restored);
    assert.equal(label.textContent,'Player 1');assert.equal(label.dataset.reading,'confirmed');
    assert(!label.classList.contains('retained-identity'));
    tick(10);const replaced=fresh();replaced.table_context.seats[0].occupant_epoch+=1;
    replaced.table_context.seats[0].identity=null;replaced.table_context.seats[0].continuity='uncertain';
    replaced.table_context.seats[0].status='unknown';accept(replaced);
    assert.equal(label.textContent,'Seat status pending');
  } else if (input.scenario === 'context-replacement') {
    select(1).listeners.click(); const focus = document.activeElement;
    tick(10); const next = fresh(); const seat = next.table_context.seats[0];
    seat.occupant_epoch += 1; seat.identity = 'Replacement'; // Delayed old-owner profile must detach.
    accept(next); persistent(); assert.equal(document.activeElement, focus);
    assert(nodes.get('player-title').textContent.includes('Replacement'));
    assert(nodes.get('player-association').textContent.includes('Occupant changed'));
    assert(nodes.get('player-stats-status').textContent.startsWith('Unknown')); assert.equal(stack(1).textContent, '-');
    tick(10); const vacant = fresh(); vacant.table_context.seats[0].occupancy = 'empty';
    vacant.table_context.seats[0].identity = null; accept(vacant); assert.equal(stack(1).textContent, '-');
    assert(seats[0].textContent.includes('Empty seat')); assert(!seats[0].textContent.includes('Badge'));
  } else if (input.scenario === 'context-uncertain-owner') {
    select(1).listeners.click(); assert(nodes.get('player-stats-status').textContent.startsWith('Unknown'));
    assert(/Name pending|Seat status pending/.test(nodes.get('player-title').textContent));
    assert.equal(nodes.get('occupancy-summary').textContent, input.occupancy || 'Occupancy uncertain');
  } else if (input.scenario === 'context-pending-labels') {
    const names=seats.map(seat=>seat.childNodes[0].childNodes[0].childNodes[1].textContent);
    assert.equal(names[0],'Name pending');assert.equal(names[1],'Empty seat');assert.equal(names[2],'Seat status pending');
    assert(!seats.some(seat=>seat.textContent.includes('Unknown player')));
    assert.equal(nodes.get('occupancy-summary').textContent,'Occupancy uncertain');
  } else if (input.scenario === 'context-table-boundary') {
    select(1).listeners.click(); tick(10); const next = fresh(); next.table_context.table_context_id = 'another-table';
    accept(next); persistent(); assert.equal(stack(1).textContent, '-'); assert.equal(nodes.get('amount-pot').textContent, '-');
    assert(nodes.get('player-stats-status').textContent.startsWith('Unknown'));
    assert.equal(nodes.get('history-folds').textContent, '2', 'UI must not invent history resets or betting order');
    const replay = pulse(); accept(replay);
    assert(seats.every(seat => seat.childNodes[0].childNodes[0].childNodes[1].dataset.reading==='last-read'));
    assert(seats.every(seat => JSON.parse(seat.childNodes[0].childNodes[0].childNodes[1].dataset.captureRef).sequence===next.table_context.capture.sequence));
  } else if (input.scenario === 'context-receipts') {
    const journal = window.monitorRenderReceipts.read(); assert(journal.clock_origins.capture_monotonic.includes('not comparable'));
    const role = journal.receipts.filter(receipt => receipt.field === 'role').at(-1);
    assert.deepEqual(JSON.parse(JSON.stringify(role.capture)), input.snapshot.table_context.capture);
    assert.equal(role.published_at_unix_ms, wall); assert.equal(role.seat, null);
    const pot = journal.receipts.filter(receipt => receipt.field === 'pot_size').at(-1);
    assert.equal(pot.capture.sequence, input.snapshot.partial_observation.capture.sequence);
    assert.notEqual(pot.capture.sequence, role.capture.sequence);
    const original = nodes.get('amount-pot').dataset.publishedAtUnixMs;
    window.monitorRenderReceipts.reset(); tick(100); accept(pulse());
    assert.equal(window.monitorRenderReceipts.read().receipts.length, 0);
    assert.equal(nodes.get('amount-pot').dataset.publishedAtUnixMs, original);
    tick(901); test.refreshClocks();
    const expired = window.monitorRenderReceipts.read().receipts.find(receipt => receipt.field === 'pot_size');
    assert.equal(expired.status, 'last-read'); assert.equal(expired.capture.captured_at_unix_ms, pot.capture.captured_at_unix_ms);
    assert.equal(expired.published_at_unix_ms, wall);
  } else if (input.scenario === 'context-metric-validation') {
    select(1).listeners.click(); const rows = nodes.get('player-stats').childNodes;
    input.metricValues.forEach((expected, index) => assert.equal(rows[index].childNodes[1].textContent, expected));
    input.metricStates.forEach((expected, index) => assert.equal(rows[index].childNodes[2].textContent, expected));
    assert.equal(rows.length, 4); persistent();
    assert(nodes.get('player-evidence').hidden === !!input.noEvidence);
  } else if (input.scenario === 'context-popup') {
    select(1).listeners.click(); const metric = nodes.get('player-stats').childNodes[0].childNodes[1];
    const receipt = JSON.parse(metric.dataset.captureRef);
    assert.equal(receipt.width, 260); assert.equal(receipt.height, 180);
    assert.equal(receipt.parent_capture.width, input.snapshot.capture.width);
    assert.equal(receipt.sha256, 'c'.repeat(64)); assert.equal(receipt.parent_capture.sha256, 'e'.repeat(64));
    assert(receipt.non_atomic); assert(nodes.get('player-stats-source').textContent.includes('separate popup, non-atomic'));
    assert.equal(metric.textContent, '12.5%');
  } else if (input.scenario === 'context-receipt-cap') {
    const target = nodes.get('amount-pot');
    window.monitorRenderReceipts.reset();
    const capacity = window.monitorRenderReceipts.read().capacity;
    for (let i = 0; i < capacity + 3; i += 1) test.publishField(target, 'bounded_probe', String(i), 'unknown', null);
    const journal = window.monitorRenderReceipts.read();
    assert.equal(journal.receipts.length, capacity); assert.equal(journal.dropped, 3);
    assert.equal(journal.receipts[0].value, '3');
    window.monitorRenderReceipts.reset(); assert.equal(window.monitorRenderReceipts.read().dropped, 0);
    assert.equal(window.monitorRenderReceipts.read().receipts.length, 0);
  } else if (input.scenario === 'context-calm-retained') {
    tick(1001); test.refreshClocks(); const pot=nodes.get('amount-pot');
    assert.equal(pot.dataset.reading,'last-read'); const mutations=pot.mutations;
    const stacks=seats.map((_,index)=>stack(index+1).mutations);
    for(let i=0;i<5;i+=1) {tick(100);test.refreshClocks();persistent();}
    assert.equal(pot.mutations,mutations);assert.equal(pot.textContent,'123.45 chips');
    stacks.forEach((value,index)=>assert.equal(stack(index+1).mutations,value));
  } else if (input.scenario === 'context-caption-unknown') {
    select(1).listeners.click(); tick(10); const missing=fresh(); missing.table_context.table_context_id=null;
    accept(missing); assert.equal(nodes.get('amount-pot').textContent,'123.45 chips');
    assert(nodes.get('player-stats-status').textContent.startsWith('Unknown'));
    tick(10);accept(fresh());assert(seats[0].textContent.includes('Player 1'));
    assert(nodes.get('player-stats-status').textContent.includes('Last observed client-displayed'));
    assert.equal(nodes.get('amount-pot').textContent,'123.45 chips');persistent();
  } else if (input.scenario === 'context-source-clock') {
    select(1).listeners.click(); const before=nodes.get('player-stats-status').textContent;
    const metric=nodes.get('player-stats').childNodes[0].childNodes[1], original=metric.dataset.captureRef;
    assert(before.includes('1m+ source age'));wall-=100;mono+=100;test.refreshClocks();
    assert(nodes.get('player-stats-status').textContent.includes('1m+ source age'));
    assert.equal(metric.dataset.captureRef,original);
  } else if (input.scenario === 'context-atomic-missing') {
    select(1).listeners.click(); assert(nodes.get('player-stats').textContent.includes('12.5%'));
    tick(10);const next=fresh(), stats=next.table_context.seats[0].stats;
    stats.capture=structuredClone(next.table_context.capture);stats.captured_at_unix_ms=stats.capture.captured_at_unix_ms;
    stats.metrics={};accept(next);
    assert(nodes.get('player-stats').childNodes.every(row=>row.childNodes[1].textContent==='-'));
    assert(nodes.get('player-stats').childNodes.every(row=>row.childNodes[2].textContent==='missing'));
  }
}
if (input.scenario.startsWith('experimental-')) {
  const panel = () => !nodes.get('experimental-panel').hidden;
  const contents = () => nodes.get('experimental-candidates').textContent;
  const cleared = () => { assert(!panel()); assert.equal(contents(), ''); assert.equal(nodes.get('experimental-age').textContent, ''); };
  const baselinePot = nodes.get('amount-pot').textContent;
  const notAdmitted = () => {
    assert.equal(nodes.get('amount-pot').textContent, baselinePot);
    assert.equal(nodes.get('acting-seat').textContent, '-'); assert.equal(nodes.get('amount-call').textContent, '-');
    assert(nodes.get('wagers-reading').hidden); assert(nodes.get('controls-reading').hidden); assert(nodes.get('metrics-readings').hidden);
    assert(nodes.get('history-panel').hidden); assert.equal(nodes.get('history-events').childNodes.length, 0);
    assert(!nodes.get('seat-readings').textContent.includes('Acting'));
    assert.equal(nodes.get('action-amount').textContent, '-');
  };
  if (input.scenario === 'experimental-live') {
    assert(panel()); assert(contents().includes('Unvalidated numeric text: ' + input.snapshot.experimental_candidates.numeric_text));
    assert(contents().includes('NOT a fitted p6 floor')); assert(contents().includes('Glyph scores:'));
    assert(nodes.get('experimental-age').textContent.includes('500 ms original source age')); notAdmitted();
    wall += 500; mono += 500; accept(input.snapshot); assert(panel());
    assert(nodes.get('experimental-age').textContent.includes('1000 ms original source age'));
    mono += 501; wall += 501; test.refreshClocks(); cleared();
    const replay = structuredClone(input.snapshot); replay.event_seq += 1;
    replay.experimental_candidates.remaining_ms = 4000; replay.experimental_candidates.expires_at_unix_ms = wall + 3000;
    accept(replay); cleared();
    assert(!nodes.get('monitor-readings').hidden, 'numeric last-read retention is independent');
    assert(nodes.get('pot-reason').textContent.includes('Last read'));
    assert.equal(nodes.get('observation-title').textContent, 'Last-read amounts');
  } else if (input.scenario === 'experimental-long') {
    assert(panel());
    for (let step = 1; step <= 4; step += 1) {
      wall += 1000; mono += 1000;
      const next = structuredClone(input.snapshot); next.event_seq += step;
      next.capture.last_heartbeat_unix_ms = wall; next.capture_session.updated_at_unix_ms = wall;
      next.partial_observation = null; next.experimental_candidates.remaining_ms = 4500 - step * 1000;
      accept(next); assert(panel());
      assert.equal(nodes.get('observation-title').textContent, 'Last-read amounts');
      assert(nodes.get('pot-reason').textContent.includes('Last read'));
      assert(nodes.get('experimental-age').textContent.includes(`${500 + step * 1000} ms original source age`));
    }
    wall += 501; mono += 501; test.refreshClocks(); cleared();
    assert(!nodes.get('monitor-readings').hidden); assert.equal(nodes.get('observation-title').textContent, 'Last-read amounts');
  } else if (input.scenario === 'experimental-scene') {
    assert(panel()); assert(contents().includes('scene/marker guesses')); assert(contents().includes('Badge guess'));
    assert(contents().includes('raise / score 0.990 / unvalidated / no fitted floor'));
    assert(contents().includes('Acting-marker guess')); notAdmitted();
    const next = structuredClone(input.snapshot); next.event_seq += 1; next.experimental_candidates = null;
    accept(next); cleared(); notAdmitted();
  } else if (input.scenario === 'experimental-unknown') {
    assert(panel()); assert(contents().includes('Unknown / no numeric candidate'));
    assert(!contents().includes('Unvalidated numeric text: 0')); notAdmitted();
  } else if (input.scenario === 'experimental-boundary') {
    assert(panel()); const next = structuredClone(input.snapshot); next.event_seq += 1;
    for (const [key, fields] of Object.entries(input.update)) Object.assign(next[key] ||= {}, fields);
    if (input.candidate) Object.assign(next.experimental_candidates, input.candidate);
    if (input.message) next.message = input.message;
    accept(next); cleared();
  } else if (input.scenario === 'experimental-late') {
    assert(panel()); const next = structuredClone(input.snapshot); next.event_seq += 1;
    next.experimental_candidates.generation -= 1; next.experimental_candidates.numeric_text = '0';
    next.experimental_candidates.glyph_scores = [.99]; accept(next);
    assert(panel()); assert(!contents().includes('Unvalidated numeric text: 0')); notAdmitted();
  } else if (input.scenario === 'experimental-disconnect') {
    assert(panel()); test.suspend(); cleared();
    test.resume(); accept(input.snapshot); cleared();
  } else if (input.scenario === 'experimental-blocked') { cleared(); }
}
if (input.scenario.startsWith('analysis-')) {
  const noAdvice = () => {
    assert.equal(nodes.get('action-amount').textContent, '-');
    assert(nodes.get('action-amount-wrap').hidden);
    assert.equal(nodes.get('analysis-status').textContent, 'Analysis unavailable');
    assert(!nodes.get('action-reason').textContent.includes('Estimated EV:'));
  };
  const analysis = () => {
    assert(visible()); assert.equal(nodes.get('action-title').textContent, 'Experimental recommendation');
    assert.equal(nodes.get('action-move').textContent, input.action || 'Call');
    assert.equal(nodes.get('action-amount').textContent, input.amount || '0.50 chips');
    assert.equal(nodes.get('analysis-status').textContent, 'Experimental analysis');
    assert(nodes.get('action-reason').textContent.includes('quality_approved: false'));
    assert(nodes.get('action-reason').textContent.includes('Estimated EV: 12.50 (native units)'));
    assert(!nodes.get('metrics-readings').hidden);
    assert.equal(nodes.get('metric-rank').textContent, 'High Card');
    assert.equal(nodes.get('metric-odds').textContent, input.odds || '25.0%');
    assert.equal(nodes.get('metric-draw-outs').textContent, '9');
    assert.equal(nodes.get('metric-equity').textContent, '62.0%');
    assert(nodes.get('model-status').textContent.includes(`quality ${input.quality || 'failed'}`));
    assert.equal(nodes.get('action-move').tagName, 'p');
    assert(nodes.get('control-states').childNodes.every(item => item.tagName === 'li'));
  };
  let eventSequence = input.snapshot.event_seq;
  const next = (generation = input.snapshot.observation?.generation, captured = input.snapshot.observation?.captured_at_unix_ms) => {
    const raw = structuredClone(input.snapshot); raw.event_seq = ++eventSequence;
    raw.capture.last_heartbeat_unix_ms = wall; raw.capture_session.updated_at_unix_ms = wall;
    raw.capture.generation = generation;
    if (raw.observation) Object.assign(raw.observation, { generation, captured_at_unix_ms: captured });
    if (raw.advice) Object.assign(raw.advice, { generation, captured_at_unix_ms: captured });
    return raw;
  };
  if (input.scenario === 'analysis-valid') analysis();
  else if (input.scenario === 'analysis-blocked') {
    noAdvice();
    if (input.metricsBlocked) assert(nodes.get('metrics-readings').hidden);
  } else if (input.scenario === 'analysis-metrics-filtered') {
    for (const id of input.unknown) assert.equal(nodes.get(id).textContent, '-', id);
    if (input.allUnknown) assert(nodes.get('metrics-readings').hidden);
  } else if (input.scenario === 'analysis-later-decision') {
    noAdvice(); const raw = next(); raw.advice = input.advice; raw.server.advice_ready = true; accept(raw); analysis();
  } else if (input.scenario === 'analysis-boundary') {
    analysis(); const raw = next(2);
    for (const [key, fields] of Object.entries(input.update || {})) Object.assign(raw[key], fields);
    if (input.message) raw.message = input.message;
    accept(raw); noAdvice(); assert(nodes.get('metrics-readings').hidden);
  } else if (input.scenario === 'analysis-expiry') {
    analysis(); wall += 500; mono += 500; accept(input.snapshot); analysis();
    wall += 501; mono += 501; test.refreshClocks(); noAdvice(); assert(nodes.get('metrics-readings').hidden);
    for (const gen of [1, 2]) {
      const replay = next(gen);
      for (const item of [replay.observation, replay.advice]) Object.assign(item, { expires_at_unix_ms: wall + 1000, remaining_ms: 1000 });
      accept(replay); noAdvice(); assert(nodes.get('metrics-readings').hidden);
    }
    const fresh = next(3, wall - 100);
    for (const item of [fresh.observation, fresh.advice]) Object.assign(item, { expires_at_unix_ms: wall + 1000, remaining_ms: 1000 });
    accept(fresh); analysis();
  } else if (input.scenario === 'analysis-short-lease') {
    analysis(); wall += input.rollback ? -100 : 501; mono += 501; test.refreshClocks(); noAdvice(); assert(!nodes.get('metrics-readings').hidden);
    const replay = next(2); Object.assign(replay.advice, { expires_at_unix_ms: replay.observation.expires_at_unix_ms, remaining_ms: 499 });
    accept(replay); noAdvice();
  } else if (input.scenario === 'analysis-original-expiry') {
    analysis(); wall += 100; mono += 100;
    const replay = next(input.relabel ? 2 : 1);
    for (const item of [replay.observation, replay.advice]) Object.assign(item, { expires_at_unix_ms: item.expires_at_unix_ms + 500, remaining_ms: 1400 });
    accept(replay); noAdvice(); assert(nodes.get('metrics-readings').hidden);
  } else if (input.scenario === 'analysis-disconnect') {
    analysis(); test.suspend(); noAdvice(); assert(nodes.get('metrics-readings').hidden);
    test.resume(); accept(input.snapshot); noAdvice();
  } else if (input.scenario === 'analysis-partial') {
    noAdvice(); assert(nodes.get('metrics-readings').hidden); assert(nodes.get('controls-reading').hidden);
    assert.equal(nodes.get('acting-seat').textContent, '-');
    assert(!nodes.get('board-cards').textContent.includes('No community cards'));
  }
  assert(![...nodes.values()].some(item => item.textContent.includes('PRIVATE') || item.textContent.includes('<script>')));
}
"""


POLL_CHECKS = r"""
(async () => {
  const requests = []; let pending = 0, maximum = 0, respond;
  context.fetch = (path, options) => {
    requests.push({ path, options }); pending += 1; maximum = Math.max(maximum, pending);
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => { pending -= 1; reject(Error('aborted')); }, { once: true });
      respond = () => {
        pending -= 1; let read = false;
        resolve({ ok: true, headers: { get: name => name === 'content-type' ? 'application/json' : null },
          body: { getReader: () => ({ read: async () => {
            if (read) return { done: true }; read = true;
            return { done: false, value: new TextEncoder().encode(JSON.stringify(input.snapshot)) };
          } }) } });
      };
    });
  };
  const first = test.poll(); await test.poll(); await test.poll();
  assert.equal(requests.length, 1); respond(); await first;
  test.loadReference(); assert.equal(requests.length, 1);
  const second = test.poll(); test.suspend(); test.resume(); await test.poll();
  assert.equal(requests.length, 2); assert(requests[1].options.signal.aborted); await second;
  const third = test.poll(); assert.equal(requests.length, 3); respond(); await third;
  assert.equal(maximum, 1); assert.equal(pending, 0);
  for (const { path, options } of requests) {
    assert.equal(path, '/api/state'); assert.equal(options.method, 'GET');
    assert.equal(options.cache, 'no-store'); assert.equal(options.redirect, 'error');
  }
  console.log('offline UI read-only polling: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


STOP_CHECKS = r"""
(async () => {
  const button = nodes.get('stop-capture'), requests = []; let resolve, reject;
  const response = (status, data, extra = {}) => {
    let read = false;
    return { status, ok: status === 200, headers: { get: name => name === 'content-type' ?
      (extra.contentType || 'application/json') : extra.length || null }, body: { getReader: () => ({
        read: async () => { if (read) return { done: true }; read = true;
          return { done: false, value: new TextEncoder().encode(JSON.stringify(data)) }; }, cancel: async () => {} }) } };
  };
  context.fetch = (path, options) => {
    requests.push({ path, options });
    if (options.method === 'GET') return Promise.resolve(response(200, input.snapshot));
    return new Promise((ok, fail) => { resolve = ok; reject = fail; });
  };
  assert.equal(requests.length, 0); test.loadReference(); assert.equal(requests.length, 0);
  if (input.scenario === 'stop-disabled') {
    if (input.hidden) { document.hidden = true; test.suspend(); }
    assert(button.disabled); await button.listeners.click(); assert.equal(requests.length, 0);
  } else {
    assert(!button.disabled); assert.equal(button.tagName, 'button');
    const pending = button.listeners.click(); assert(button.disabled);
    await button.listeners.click(); assert.equal(requests.length, 1);
    const { path, options } = requests[0];
    assert.equal(path, '/api/capture/stop'); assert.equal(options.method, 'POST');
    assert.equal(options.mode, 'same-origin'); assert.equal(options.credentials, 'omit');
    assert.equal(options.redirect, 'error'); assert.equal(options.cache, 'no-store');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(options.body), { session_id: input.snapshot.capture_session.session_id,
      service_instance_id: input.snapshot.server.instance_id });
    if (input.scenario === 'stop-replaced') {
      const replacement = structuredClone(input.snapshot); replacement.event_seq += 1;
      if (input.replace === 'session') replacement.capture_session.session_id = 'replacement-capture';
      else replacement.server.instance_id = 'replacement-service';
      accept(replacement); assert(options.signal.aborted);
      resolve(response(200, { ok: true })); await pending;
      assert(!button.disabled); assert.equal(nodes.get('stop-capture-status').textContent, '');
    } else if (input.scenario === 'stop-disconnect') {
      test.suspend(); assert(options.signal.aborted);
      resolve(response(200, { ok: true })); await pending; assert(button.disabled);
      assert(!nodes.get('stop-capture-status').textContent.includes('Stop requested'));
    } else {
      if (input.networkError) reject(Error('PRIVATE-NETWORK'));
      else resolve(response(input.status || 200, input.response || { ok: true }, input));
      await pending;
      assert(nodes.get('stop-capture-status').textContent.includes(input.expectedStop || 'Stop requested'));
      assert(!nodes.get('stop-capture-status').textContent.includes('PRIVATE'));
      if (!input.expectedStop) {
        assert(button.disabled); assert(!visible());
        const replay = newer(2, input.snapshot.event_seq + 1); accept(replay);
        assert(!visible()); assert(button.disabled); await button.listeners.click();
        replay.event_seq += 1; replay.capture_session.status = 'stopped'; accept(replay);
        assert.equal(nodes.get('stop-capture-status').textContent, 'Capture session stopped.');
      } else if (input.status === 409) assert(button.disabled);
      else assert(!button.disabled);
    }
    assert.equal(requests.length, 1, 'never retry a POST automatically');
  }
  console.log(`offline UI ${input.scenario}: PASS`);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@unittest.skipUnless(shutil.which("node"), "Node required for synthetic DOM contracts")
class CompanionUiTests(unittest.TestCase):
    def setUp(self):
        fixture = stage2.PartialTests()
        fixture.setUp()
        fixture.reading()
        self.snapshot = fixture.state.snapshot()

    def run_ui(self, scenario, **extra):
        payload = {"scenario": scenario, "snapshot": self.snapshot,
                   "app": str(stage2.dashboard.ROOT / "scripts/dashboard/app.js"),
                   "html": str(stage2.dashboard.ROOT / "scripts/dashboard/index.html"), **extra}
        script = stage2.NODE_UI.replace("console.log(`offline UI", CHECKS + "\nconsole.log(`offline UI")
        if scenario == "context-receipt-cap":
            script = script.replace("{ normalizeSnapshot, acceptSnapshot", "{ publishField, normalizeSnapshot, acceptSnapshot")
        if scenario == "polling":
            script = stage2.NODE_UI.replace("{ normalizeSnapshot, acceptSnapshot", "{ poll, normalizeSnapshot, acceptSnapshot")
            script = script.replace("console.log(`offline UI ${input.scenario}: PASS`);", POLL_CHECKS)
        if scenario.startswith("stop-"):
            script = stage2.NODE_UI.replace("console.log(`offline UI ${input.scenario}: PASS`);", STOP_CHECKS)
        # Feed the harness through stdin rather than Windows' bounded command line.
        script = script.replace("JSON.parse(fs.readFileSync(0, 'utf8'))", json.dumps(payload))
        script = script.replace("let wall = input.snapshot.capture.last_heartbeat_unix_ms,", "let wall = input.snapshot.capture.last_heartbeat_unix_ms ?? input.snapshot.capture_session?.updated_at_unix_ms,")
        script = script.replace("vm.createContext(context);", "context.localStorage = new Proxy({}, { get() { throw Error('no storage revival'); } }); vm.createContext(context);")
        script = script.replace("getElementById: id => { assert(", "getElementById: id => { if (input.noReadingHeading && id === 'observation-title') return null; assert(")
        result = subprocess.run(["node", "-"], input=script, capture_output=True,
                                text=True, encoding="utf-8", timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def manual_session(self, mode="inference-enabled", status="capturing", **extra):
        self.snapshot["server"].update(inference_enabled=True, model_state="ready")
        self.snapshot["capture_session"] = {
            "session_id": "manual-session-a",
            "mode": mode, "status": status, "inference_enabled": mode == "inference-enabled",
            "elapsed_ms": 1000, "max_duration_ms": 600000, "remaining_ms": 599000, "max_frames": 1200,
            "recorded_frames": 2, "updated_at_unix_ms": self.snapshot["capture"]["last_heartbeat_unix_ms"],
            **extra,
        }

    def retained_session(self):
        self.manual_session(source_policy="automatic-bounded", activity_state="verifying")
        self.snapshot["server"]["instance_id"] = "service-a"
        self.snapshot["capture"]["epoch"] = self.snapshot["partial_observation"]["epoch"]
        partial = self.snapshot["partial_observation"]
        partial["pot_size_text"] = None
        for seat in partial["seats"]:
            seat["displayed_stack"] = 0 if seat["seat"] == 4 else seat["seat"] * 100
            partial["field_statuses"][f"seats.{seat['seat']}.displayed_stack"] = {"status": "accepted", "reason": None}

    def full_analysis(self):
        """Synthetic public native-full projection, not a claim about the pinned model."""
        self.setUp()
        self.manual_session()
        partial = self.snapshot["partial_observation"]
        source = {key: partial[key] for key in ("generation", "epoch", "captured_at_unix_ms", "expires_at_unix_ms", "remaining_ms")}
        source.update(session_id=self.snapshot["session_id"], source_id="0123456789abcdef")
        self.snapshot["capture"].update(source_id=source["source_id"], generation=source["generation"], epoch=source["epoch"])
        self.snapshot["server"].update(instance_id="service-a", advice_ready=True)
        self.snapshot["partial_observation"] = None
        self.snapshot["observation"] = {**source, "experimental": True, "quality_approved": False,
            "role": "your_turn", "hero_seated": True, "action_required": True, "hero_seat": 2,
            "game_phase": "flop", "hero_cards": [{"rank": "A", "suit": "s"}, {"rank": "K", "suit": "s"}],
            "board": [{"rank": "Q", "suit": "s"}, {"rank": "7", "suit": "c"}, {"rank": "2", "suit": "s"}],
            "available_actions": ["fold", "call", "raise"],
            "controls": [{"action": action, "presence": "present", "enabled": "enabled"} for action in ("fold", "call", "raise")],
            "amounts": {"pot_size": 150, "to_call": 50, "hero_chips": 10000, "min_raise_to": 100, "max_raise_to": 10000},
            "metrics": {"hand_rank": "High Card", "pot_odds": {"seat": None, "required_equity_pct": 25},
                        "draw": {"outs": 9, "next_card_pct": 19.148936, "by_river_pct": 34.967623}, "equity_pct": 62},
            "wagers": [{"seat": 3, "amount": 50}], "field_statuses": {}}
        self.snapshot["advice"] = {**source, "experimental": True, "quality_approved": False,
            "action": "call", "amount": 50, "ev": 12.5, "equity_pct": 62,
            "pot_odds_pct": 25, "break_even_pct": 25, "confidence": .7}

    def test_source_bound_full_native_analysis_renders_without_quality_promotion_or_game_buttons(self):
        self.full_analysis()
        self.snapshot["advice"].update(reason="PRIVATE <script>", opponent="PRIVATE", label="PRIVATE")
        self.snapshot["observation"].update(reason="PRIVATE", player="PRIVATE")
        self.run_ui("analysis-valid")

    def test_native_dashboard_projection_round_trips_into_node_without_contract_translation(self):
        self.full_analysis()
        metrics = copy.deepcopy(self.snapshot["observation"]["metrics"])
        fixture = native.NativeProjectionTests()
        fixture.setUp()
        source = fixture.fresh(metrics=metrics)
        fixture.state.ingest(native.native_decision(source, ev=12.5, equity=.62))
        self.snapshot = fixture.state.snapshot()
        # The HTTP layer supplies the current service identity and session receipt.
        self.manual_session()
        self.snapshot["server"]["instance_id"] = "service-a"
        self.run_ui("analysis-valid")

    def test_other_typed_quality_states_do_not_veto_experimental_analysis(self):
        self.full_analysis()
        for quality, label in (("passed", "passed"), ("unknown", "unknown"), ("PRIVATE <script>", "unknown")):
            with self.subTest(quality=quality):
                self.snapshot["server"]["quality_gate"] = quality
                self.run_ui("analysis-valid", quality=label)

    def test_native_supported_actions_remain_plain_text_including_short_all_in_calls(self):
        for action, amount, label, shown in (("fold", 0, "Fold", "-"), ("raise", 250, "Raise", "2.50 chips"),
                                           ("check", 0, "Check", "-"), ("allin", 40, "All-in", "0.40 chips")):
            with self.subTest(action=action):
                self.full_analysis()
                metrics = copy.deepcopy(self.snapshot["observation"]["metrics"])
                fixture = native.NativeProjectionTests()
                fixture.setUp()
                source = native.native_observation(fixture.clock)
                odds = .25
                if action == "check":
                    source.update(to_call=0, available_actions=["check", "raise"])
                    metrics["pot_odds"] = None
                    odds = None
                elif action == "allin":
                    source.update(hero_chips=40, available_actions=["fold", "allin"], min_raise_to=None, max_raise_to=None)
                    source["verified_fields"] = source["verified_fields"][:-2]
                    metrics["pot_odds"] = None
                    odds = 40 / 190
                for control in source["controls"]:
                    offered = ("allin" if control["action"] == "all_in" else control["action"]) in source["available_actions"]
                    control.update(presence="present" if offered else "unknown", enabled="enabled" if offered else "unknown")
                source["metrics"] = metrics
                source = fixture.fresh(**source)
                fixture.state.ingest(native.native_decision(source, action=action, amount=amount, ev=12.5,
                                                           equity=.62, pot_odds=odds, break_even=odds))
                self.snapshot = fixture.state.snapshot()
                self.manual_session()
                self.snapshot["server"]["instance_id"] = "service-a"
                self.run_ui("analysis-valid", action=label, amount=shown, odds="-" if action in ("check", "allin") else "25.0%")

    def test_decision_can_arrive_after_observation_without_read_only_snapshot_veto(self):
        self.full_analysis()
        advice = self.snapshot["advice"]
        self.snapshot["advice"] = None
        self.snapshot["server"]["advice_ready"] = False
        self.run_ui("analysis-later-decision", advice=advice)

    def test_analysis_requires_exact_source_generation_epoch_and_original_capture(self):
        for fields in ({"session_id": "other"}, {"source_id": "1111111111111111"}, {"generation": 2},
                       {"epoch": 2}, {"captured_at_unix_ms": 1}, {"quality_approved": True},
                       {"experimental": False}, {"remaining_ms": 1001}):
            with self.subTest(fields=fields):
                self.full_analysis()
                self.snapshot["advice"].update(fields)
                self.run_ui("analysis-blocked")
        for owner, fields in (("capture", {"source_id": None}), ("capture", {"source_id": "1111111111111111"}),
                              ("capture", {"generation": 2}), ("server", {"instance_id": None}),
                              ("observation", {"session_id": "other"}), ("observation", {"quality_approved": True}),
                              ("observation", {"experimental": False}), ("observation", {"board": []})):
            with self.subTest(owner=owner, fields=fields):
                self.full_analysis()
                self.snapshot[owner].update(fields)
                self.run_ui("analysis-blocked", metricsBlocked=True)
        for fields in ({"model_state": "failed"}, {"model_state": "loading"}, {"inference_enabled": False}):
            with self.subTest(no_receipt=fields):
                self.full_analysis()
                self.snapshot.pop("capture_session")
                self.snapshot["server"].update(fields)
                self.run_ui("analysis-blocked", metricsBlocked=True)

    def test_illegal_or_malformed_recommendations_are_filtered_not_rendered_as_feed_prose(self):
        for fields in ({"action": "bet"}, {"action": "PRIVATE <script>"}, {"action": "__proto__"},
                       {"action": "check"}, {"action": "fold", "amount": 50}, {"action": "all_in", "amount": 10000},
                       {"action": "raise", "amount": 99}, {"action": "raise", "amount": 10001},
                       {"amount": 49}, {"amount": -1}, {"amount": 1.5}, {"amount": "50"},
                       {"ev": float("nan")}, {"ev": float("inf")}, {"ev": 8589934591},
                       {"equity_pct": 101}, {"equity_pct": "62"}, {"confidence": 1.1},
                       {"pot_odds_pct": -1}, {"break_even_pct": True}):
            with self.subTest(fields=fields):
                self.full_analysis()
                self.snapshot["advice"].update(fields)
                self.run_ui("analysis-blocked")
        for fields in ({"role": "uncertain"}, {"action_required": False}, {"hero_seated": False},
                       {"hero_cards": []}, {"available_actions": ["raise"]}, {"available_actions": ["call", "call"]},
                       {"controls": [{"action": "call", "presence": "present", "enabled": "unknown"}]},
                       {"controls": [{"action": "call", "presence": "present", "enabled": "enabled"}] * 2}):
            with self.subTest(fields=fields):
                self.full_analysis()
                self.snapshot["observation"].update(fields)
                self.run_ui("analysis-blocked")

    def test_closed_metric_vocabulary_finite_ranges_and_phase_filter(self):
        for fields, unknown in (({"hand_rank": "PRIVATE <script>"}, ["metric-rank"]),
                                ({"equity_pct": float("inf")}, ["metric-equity"]),
                                ({"equity_pct": True}, ["metric-equity"]),
                                ({"pot_odds": {"seat": 3, "required_equity_pct": 25}}, ["metric-odds"]),
                                ({"draw": {"outs": 48, "next_card_pct": 20, "by_river_pct": 30}}, ["metric-draw-outs"]),
                                ({"draw": {"outs": 9, "next_card_pct": 40, "by_river_pct": 30}}, ["metric-draw-next"])):
            with self.subTest(fields=fields):
                self.full_analysis()
                self.snapshot["observation"]["metrics"].update(fields)
                self.run_ui("analysis-metrics-filtered", unknown=unknown)
        self.full_analysis()
        self.snapshot["observation"]["metrics"] = {}
        self.run_ui("analysis-metrics-filtered", unknown=["metric-rank", "metric-equity", "metric-odds", "metric-draw-outs"], allUnknown=True)
        self.full_analysis()
        self.snapshot["observation"].update(game_phase="preflop", board=[])
        self.run_ui("analysis-metrics-filtered", unknown=["metric-draw-outs", "metric-draw-next", "metric-draw-river"])

    def test_partial_chips_and_unknown_board_cannot_be_promoted_to_analysis(self):
        self.full_analysis()
        full, advice = self.snapshot["observation"], self.snapshot["advice"]
        self.setUp()
        self.retained_session()
        self.snapshot["advice"] = advice
        self.snapshot["server"]["advice_ready"] = True
        self.snapshot["partial_observation"].update(board_slots=[None] * 5, board_count=None, game_phase=None,
                                                   metrics=full["metrics"], available_actions=["call"], action_required=True)
        self.run_ui("analysis-partial")

    def test_full_analysis_and_recommendation_leases_never_renew_on_poll_or_generation_relabel(self):
        self.full_analysis()
        self.run_ui("analysis-expiry")
        for relabel in (False, True):
            with self.subTest(relabel=relabel):
                self.run_ui("analysis-original-expiry", relabel=relabel)
        self.full_analysis()
        self.snapshot["advice"]["expires_at_unix_ms"] -= 500
        self.snapshot["advice"]["remaining_ms"] = 500
        self.run_ui("analysis-short-lease")
        self.run_ui("analysis-short-lease", rollback=True)
        self.full_analysis()
        self.snapshot["advice"].update(expires_at_unix_ms=self.snapshot["capture"]["last_heartbeat_unix_ms"], remaining_ms=0)
        self.run_ui("analysis-blocked")

    def test_capture_service_source_session_loss_clears_analysis(self):
        for update in ({"capture": {"fresh_capture": False}}, {"capture": {"source_id": "1111111111111111"}},
                       {"capture": {"epoch": 2}}, {"capture": {"width": 999}},
                       {"server": {"instance_id": "service-b"}}, {"server": {"model_state": "failed"}},
                       {"capture_session": {"status": "stopped"}}, {"capture_session": {"session_id": "another"}}):
            with self.subTest(update=update):
                self.full_analysis()
                self.run_ui("analysis-boundary", update=update)
        self.full_analysis()
        self.run_ui("analysis-boundary", message="source-unavailable")
        self.run_ui("analysis-disconnect")

    def test_stop_capture_is_explicit_exact_bound_post_and_clears_current_readings(self):
        self.retained_session()
        self.run_ui("stop-success")
        self.manual_session(mode="capture-only")
        self.run_ui("stop-success")

    def test_stop_capture_requires_current_service_and_fresh_capturing_receipt(self):
        for fields in ({"status": "idle"}, {"status": "stopped"}, {"session_id": None}, {"updated_at_unix_ms": 0}):
            with self.subTest(fields=fields):
                self.setUp()
                self.retained_session()
                self.snapshot["capture_session"].update(fields)
                self.run_ui("stop-disabled")
        self.setUp()
        self.retained_session()
        self.snapshot["server"]["instance_id"] = None
        self.run_ui("stop-disabled")
        self.retained_session()
        self.run_ui("stop-disabled", hidden=True)

    def test_stop_capture_filters_responses_and_never_retries_automatically(self):
        self.retained_session()
        for extra in ({"status": 409, "response": {"error": "capture-session-unavailable"}, "expectedStop": "no longer available"},
                      {"status": 400, "response": {"error": "invalid-request"}, "expectedStop": "rejected"},
                      {"status": 403, "response": {"error": "PRIVATE"}, "expectedStop": "origin was rejected"},
                      {"response": {"ok": True, "PRIVATE": "PRIVATE"}, "expectedStop": "not confirmed"},
                      {"response": {"ok": "true"}, "expectedStop": "not confirmed"},
                      {"status": 500, "response": {"error": "PRIVATE"}, "expectedStop": "not confirmed"},
                      {"networkError": True, "expectedStop": "not confirmed"},
                      {"contentType": "text/html", "expectedStop": "not confirmed"},
                      {"length": "9999999", "expectedStop": "not confirmed"}):
            with self.subTest(extra=extra):
                self.run_ui("stop-response", **extra)

    def test_stop_completion_cannot_mutate_replaced_service_session_or_disconnected_page(self):
        self.retained_session()
        for replace in ("service", "session"):
            self.run_ui("stop-replaced", replace=replace)
        self.run_ui("stop-disconnect")

    def sustained_session(self, evidence_reason=None, **extra):
        self.retained_session()
        evidence = {
            "status": "ended" if evidence_reason else "active", "stop_reason": evidence_reason,
            "elapsed_ms": 600000 if evidence_reason == "duration-limit" else 1000,
            "max_duration_ms": 600000, "max_frames": 1200, "max_bytes": 1073741824,
            "recorded_frames": 1200 if evidence_reason == "frame-limit" else 2,
            "recorded_bytes": 1073741700 if evidence_reason == "disk-limit" else 200,
        }
        self.snapshot["capture_session"].update(
            receipt_version=2, source_policy="automatic-sustained", activity_state="active",
            experimental_bet_action=False, stop_reason=None, max_duration_ms=None, max_frames=None, remaining_ms=None,
            elapsed_ms=601000 if evidence_reason else 1000, recorded_frames=evidence["recorded_frames"],
            recorded_bytes=evidence["recorded_bytes"], evidence=evidence, **extra)

    def test_sustained_more_than_ten_minutes_and_1200_acquisitions_keeps_same_owner_after_evidence_ends(self):
        self.sustained_session()
        self.run_ui("sustained-long")

    def test_coarse_monitor_ages_keep_precise_diagnostics_and_immediate_expiry(self):
        self.sustained_session()
        self.run_ui("retained-calm-clock")

    def test_sustained_evidence_time_frame_and_byte_caps_do_not_close_observation_or_retention(self):
        for reason in ("duration-limit", "frame-limit", "disk-limit"):
            with self.subTest(reason=reason):
                self.sustained_session(evidence_reason=reason)
                self.run_ui("sustained-ended")
                self.run_ui("retained-six")

    def test_sustained_verifying_or_unknown_role_keeps_independent_numbers_without_manual_history_gate(self):
        self.sustained_session()
        self.snapshot["capture_session"]["activity_state"] = "verifying"
        self.snapshot["partial_observation"].update(role="observing", hero_seated=False)
        self.snapshot["partial_observation"]["seats"][0].update(acting=True, occupied=True, scene_fields=["acting", "occupied"])
        self.snapshot["history"] = {"state": "partial", "counts": {"folds": 2}, "gaps": 3,
                                    "events": [{"kind": "action", "action": "fold", "seat": 2}]}
        self.run_ui("sustained-verifying")

    def test_sustained_five_second_individual_reading_ttl_is_not_renewed_by_owner_heartbeats(self):
        self.sustained_session(evidence_reason="duration-limit")
        now = self.snapshot["capture"]["last_heartbeat_unix_ms"]
        self.snapshot["partial_observation"].update(captured_at_unix_ms=now, expires_at_unix_ms=now + 5000, remaining_ms=5000)
        self.run_ui("sustained-lease")

    def test_sustained_fresh_receipt_does_not_preserve_readings_from_stale_capture(self):
        self.sustained_session(evidence_reason="duration-limit")
        self.run_ui("sustained-capture-stale")

    def test_sustained_three_second_receipt_lease_is_strict_and_monotonic(self):
        self.sustained_session()
        self.run_ui("sustained-heartbeat-no-renewal")
        for age, advance in ((2500, 501), (2999, 1)):
            with self.subTest(age=age):
                self.sustained_session()
                self.snapshot["capture_session"]["updated_at_unix_ms"] -= age
                self.run_ui("sustained-receipt-stale", advance=advance)

    def test_sustained_terminal_tombstone_never_rearms_and_recovery_is_in_main_monitor(self):
        for status, reason in (("stopped", "operator-stop"), ("failed", "source-changed"),
                               ("interrupted", "child-stop-unconfirmed"), ("failed", "model-not-ready")):
            for evidence in (None, "duration-limit"):
                with self.subTest(status=status, evidence=evidence):
                    self.sustained_session(evidence_reason=evidence)
                    self.run_ui("sustained-terminal", status=status, reason=reason)
        self.sustained_session()
        self.run_ui("sustained-startup-terminal")

    def test_sustained_ended_evidence_counters_limits_and_status_cannot_be_rewritten(self):
        for rewrite in ({"status": "active", "stop_reason": None, "elapsed_ms": 1000},
                        {"recorded_frames": 1}, {"recorded_bytes": 199}, {"recorded_bytes": 201},
                        {"max_frames": 1199}):
            with self.subTest(rewrite=rewrite):
                self.sustained_session(evidence_reason="duration-limit")
                self.run_ui("sustained-evidence-no-renewal", rewrite=rewrite)

    def test_sustained_source_service_epoch_geometry_session_and_inference_loss_clear_last_reads(self):
        for extra in ({"update": {"capture": {"width": 900}}}, {"update": {"capture": {"epoch": 2}}},
                      {"update": {"server": {"instance_id": "replacement"}}},
                      {"update": {"capture_session": {"session_id": "replacement-owner"}}},
                      {"update": {"server": {"model_state": "failed"}}},
                      {"update": {"server": {"inference_enabled": False}}},
                      {"update": {"capture_session": {"inference_enabled": False}}},
                      {"update": {}, "message": "source-changed"}, {"update": {}, "message": "feed-failed"},
                      {"update": {}, "feedSession": True}, {"update": {}, "source": True}):
            with self.subTest(extra=extra):
                self.sustained_session(evidence_reason="duration-limit")
                self.run_ui("retained-boundary", **extra)

    def test_sustained_source_or_instance_replacement_cannot_rearm_the_original_owner(self):
        for extra in ({"update": {"server": {"instance_id": "replacement"}}}, {"feedSession": True},
                      {"update": {"server": {"model_state": "failed"}}},
                      {"update": {"server": {"inference_enabled": False}}},
                      {"update": {"capture_session": {"inference_enabled": False}}},
                      {"message": "source-changed"}, {"message": "source-unavailable"},
                      {"message": "capture-failed"}, {"message": "inference-failed"},
                      {"message": "model-not-ready"}, {"message": "publication-failed"},
                      {"message": "feed-failed"}, {"message": "invalid-feed-record"}, {"message": "recorder-failure"},
                      {"update": {"capture_session": {"elapsed_ms": 600999}}}):
            with self.subTest(extra=extra):
                self.sustained_session(evidence_reason="duration-limit")
                self.run_ui("sustained-source-no-rearm", **extra)

    def test_sustained_same_owner_resize_and_new_epoch_clear_all_fields_then_accept_only_fresh_new_scope(self):
        for reason in (None, "duration-limit", "frame-limit", "disk-limit"):
            for marker in (False, True):
                with self.subTest(evidence=reason, marker=marker):
                    self.sustained_session(evidence_reason=reason)
                    self.run_ui("sustained-resize", marker=marker)

    def test_sustained_brief_missing_fresh_health_never_admits_or_resets_owner_lifetime(self):
        self.sustained_session(evidence_reason="duration-limit")
        self.run_ui("sustained-resize", wait=True)
        scope = {key: self.snapshot["capture"][key] for key in ("epoch", "width", "height", "state", "fresh_capture")}
        self.snapshot["capture"].update(epoch=None, width=None, height=None, state="verifying", fresh_capture=False)
        self.run_ui("sustained-initial-health-wait", scope=scope)

    def first_live_claim(self, evidence_reason=None, **extra):
        self.setUp()
        self.sustained_session(evidence_reason=evidence_reason)
        live = copy.deepcopy(self.snapshot)
        live["session_id"] = "native-table-feed"
        live["automatic_startup"] = {"enabled": True, "status": "active", "stop_reason": None}
        self.snapshot.update(session_id="sdk-boot-feed", source="idle", partial_observation=None,
                             automatic_startup={"enabled": True, "status": "waiting-model", "stop_reason": None})
        self.snapshot["server"]["model_state"] = "loading"
        self.snapshot["capture"].update(state="unavailable", fresh_capture=False, epoch=None, width=None, height=None,
                                        last_heartbeat_unix_ms=None, frames=0)
        if extra.get("terminal"):
            self.snapshot["capture_session"].update(status="stopped", stop_reason="operator-stop")
        self.run_ui("sustained-first-live-claim", live=live, **extra)

    def test_sustained_boot_receipt_allows_first_live_feed_claim_without_premature_data_or_owner_closure(self):
        for reason in (None, "duration-limit", "frame-limit", "disk-limit"):
            with self.subTest(evidence=reason):
                self.first_live_claim(evidence_reason=reason, preclaim=True)
        self.first_live_claim(long=True)

    def test_sustained_first_claim_keeps_terminal_receipt_freshness_service_and_evidence_guards(self):
        for extra in ({"terminal": True}, {"stale": True}, {"stale": True, "rollback": True}, {"service": "replacement-service"},
                      {"rewrite": {"max_frames": 1199}}):
            with self.subTest(extra=extra):
                self.first_live_claim(evidence_reason="duration-limit", **extra)

    def test_sustained_after_first_live_claim_later_feed_service_and_owner_replacement_cannot_rearm_old_owner(self):
        for later in ("feed", "idle-feed", "service", "owner"):
            with self.subTest(later=later):
                self.first_live_claim(evidence_reason="duration-limit", later=later)

    def test_sustained_resize_does_not_reset_immutable_evidence_caps_or_frozen_counters(self):
        for reason, rewrite in ((None, {"max_frames": 1199}), ("duration-limit", {"max_frames": 1199}),
                                ("duration-limit", {"recorded_frames": 1}), ("duration-limit", {"recorded_bytes": 201})):
            with self.subTest(evidence=reason, rewrite=rewrite):
                self.sustained_session(evidence_reason=reason)
                self.run_ui("sustained-resize", marker=True, rewrite=rewrite)

    def test_sustained_hide_reveal_polling_and_page_refresh_are_passive(self):
        self.sustained_session()
        self.run_ui("sustained-hidden")
        self.run_ui("polling")
        self.snapshot["partial_observation"] = None
        self.run_ui("retained-empty")

    def test_same_owner_cannot_swap_between_bounded_and_sustained_policies(self):
        self.manual_session(source_policy="automatic-bounded", activity_state="active")
        bounded = copy.deepcopy(self.snapshot["capture_session"])
        self.sustained_session()
        sustained = copy.deepcopy(self.snapshot["capture_session"])
        self.run_ui("sustained-policy-no-upgrade", bounded=bounded)
        self.snapshot["capture_session"] = bounded
        self.run_ui("bounded-policy-no-upgrade", sustained=sustained)

    def test_sustained_strict_schema_rejects_missing_null_bounds_mixed_modes_and_malformed_evidence(self):
        self.sustained_session()
        receipt = self.snapshot["capture_session"]
        invalid = []
        for key in ("receipt_version", "session_id", "activity_state", "experimental_bet_action", "stop_reason",
                    "elapsed_ms", "updated_at_unix_ms", "max_duration_ms", "max_frames", "remaining_ms", "recorded_frames", "recorded_bytes", "evidence"):
            missing = copy.deepcopy(receipt)
            missing.pop(key)
            invalid.append(missing)
        for key, values in {
            "receipt_version": [None, 1, 3, "2", True], "session_id": [None, "", "<img>"],
            "source_policy": [None, "automatic-continuous", "manual", "automatic-bounded"],
            "activity_state": [None, "searching", "PRIVATE"], "experimental_bet_action": [None, True, "false"],
            "mode": ["capture-only"], "inference_enabled": [None, "true"], "status": ["active", "PRIVATE"],
            "stop_reason": ["PRIVATE", "operator-stop"], "max_duration_ms": [0, 600000], "max_frames": [0, 1200],
            "remaining_ms": [0, 600000], "elapsed_ms": [-1, 1.5, True, None], "updated_at_unix_ms": [0, None, True],
            "recorded_frames": [None, 3], "recorded_bytes": [None, 201],
        }.items():
            invalid.extend({**receipt, key: value} for value in values)
        for key in receipt["evidence"]:
            missing = copy.deepcopy(receipt)
            missing["evidence"].pop(key)
            invalid.append(missing)
        for fields in ({"status": "stopped"}, {"status": "ended"}, {"stop_reason": "duration-limit"},
                       {"elapsed_ms": -1}, {"elapsed_ms": 600001}, {"elapsed_ms": 600000}, {"elapsed_ms": True},
                       {"max_duration_ms": 0}, {"max_duration_ms": 600001}, {"max_frames": 0}, {"max_frames": 1201},
                       {"max_bytes": 0}, {"max_bytes": 1073741825}, {"PRIVATE": "PRIVATE"},
                       {"recorded_frames": 1201}, {"recorded_bytes": 1073741825},
                       {"status": "ended", "stop_reason": "frame-limit"},
                       {"status": "ended", "stop_reason": "duration-limit"},
                       {"status": "ended", "stop_reason": "operator-stop"}):
            forged = copy.deepcopy(receipt)
            forged["evidence"].update(fields)
            invalid.append(forged)
        self.run_ui("sustained-malformed", invalid=invalid)

    def experimental_session(self, kind="wager", text="12.50"):
        self.retained_session()
        self.snapshot["server"]["experimental_bet_action"] = True
        self.snapshot["capture_session"]["experimental_bet_action"] = True
        obs = self.snapshot["partial_observation"]
        self.snapshot["experimental_candidates"] = {
            "version": 1, "generation": 2, "epoch": obs["epoch"], "captured_at_unix_ms": obs["captured_at_unix_ms"],
            "expires_at_unix_ms": obs["expires_at_unix_ms"], "remaining_ms": obs["remaining_ms"],
            "diagnostic_only": True, "quality_approved": False, "training": "unvalidated", "geometry_status": "DRAFT",
            "human_review": "PENDING", "seat": 1, "kind": kind, "fitted_floor": None,
            "donor_pass": "p5_seat_1_stack" if kind == "wager" else None, "inherited_cutoff": .8 if kind == "wager" else None,
            "numeric_text": text if kind == "wager" else None, "glyph_scores": [.99] * len(text) if kind == "wager" and text is not None else [],
            "scene": [{"field": field, "guess": "raise" if field == "badge" else "yes" if field == "acting" else values[0],
                       "score": .99, "fitted_floor": None} for field, values in {
                           "occupied": ["occupied"], "status": ["active"], "badge": ["raise"], "dealer": ["dealer_here"],
                           "small_blind": ["small_blind_here"], "big_blind": ["big_blind_here"], "acting": ["yes"]}.items()] if kind == "scene" else [],
            "reason": "unapproved-capability" if text is not None else "empty-segmentation"}

    def test_experimental_numeric_transfer_panel_is_separate_leased_and_not_retained(self):
        self.experimental_session()
        self.run_ui("experimental-live")
        self.experimental_session(text="0")
        self.run_ui("experimental-live")

    def test_experimental_scene_guesses_do_not_become_actor_actions_or_history(self):
        self.experimental_session(kind="scene")
        self.run_ui("experimental-scene")

    def test_experimental_empty_segmentation_never_displays_zero(self):
        self.experimental_session(text=None)
        self.run_ui("experimental-unknown")

    def test_exact_candidate_five_second_expiry_clears_panel_while_numeric_last_reads_remain(self):
        self.experimental_session()
        candidate = self.snapshot["experimental_candidates"]
        candidate.update(expires_at_unix_ms=candidate["captured_at_unix_ms"] + 5000, remaining_ms=4500)
        self.run_ui("experimental-long")

    def test_last_read_caption_is_optional_and_fresh_numeric_overwrites_restore_current_caption(self):
        self.retained_session()
        self.run_ui("retained-independent")
        self.run_ui("retained-six", noReadingHeading=True)

    def test_experimental_panel_requires_both_explicit_flags_and_bounded_current_owner(self):
        self.experimental_session()
        for update in ({"server": {"experimental_bet_action": False}}, {"server": {"experimental_bet_action": "true"}},
                       {"capture_session": {"experimental_bet_action": False}}, {"capture_session": {"source_policy": "manual"}},
                       {"capture_session": {"status": "stopped"}}, {"server": {"inference_enabled": False}},
                       {"capture": {"fresh_capture": False}}, {"capture": {"epoch": None}},
                       {"capture": {"width": 900}}, {"capture": {"epoch": 2}},
                       {"server": {"instance_id": "replacement"}}, {"capture_session": {"session_id": "replacement"}}):
            with self.subTest(update=update):
                self.run_ui("experimental-boundary", update=update)
        self.run_ui("experimental-boundary", update={}, message="source-unavailable")

    def test_experimental_public_forged_proofs_floors_scores_and_hostile_text_rejected(self):
        self.experimental_session()
        for candidate in ({"training": "trained_unapproved"}, {"human_verified": True}, {"fitted_floor": .8},
                          {"inherited_cutoff": .799}, {"numeric_text": "<img>"}, {"glyph_scores": [.5] * 5},
                          {"quality_approved": True}, {"diagnostic_only": False}, {"seat": 7}):
            with self.subTest(candidate=candidate):
                self.run_ui("experimental-boundary", update={}, candidate=candidate)
        self.experimental_session(kind="scene")
        self.snapshot["experimental_candidates"]["scene"][2]["guess"] = "<script>"
        self.run_ui("experimental-blocked")

    def test_experimental_late_candidate_never_overwrites_newer_and_disconnect_drops_without_revival(self):
        self.experimental_session()
        self.run_ui("experimental-late")
        self.run_ui("experimental-disconnect")

    def test_retained_pot_and_each_physical_stack_overwrite_independently_including_zero(self):
        self.retained_session()
        self.run_ui("retained-independent")

    def test_retained_original_source_age_survives_polls_replays_and_clock_rollback_without_live_renewal(self):
        self.retained_session()
        self.run_ui("retained-age")

    def test_retained_all_six_stacks_and_pot_outlive_source_lease_only_as_last_read_display(self):
        self.retained_session()
        self.run_ui("retained-six")

    def test_retained_region_invalidation_marks_changed_and_new_field_clears_only_its_changed_label(self):
        self.retained_session()
        self.run_ui("retained-changed")

    def test_retained_source_epoch_geometry_service_and_session_boundaries_clear(self):
        self.retained_session()
        for extra in ({"update": {"capture": {"width": 900}}}, {"update": {"capture": {"height": 614}}},
                      {"update": {"capture": {"width": None}}}, {"update": {"server": {"instance_id": "service-b"}}},
                      {"update": {"server": {"instance_id": None}}},
                      {"update": {"capture": {"epoch": 2}}},
                      {"update": {"capture": {"epoch": None}}},
                      {"update": {"capture_session": {"session_id": "replacement-capture"}}},
                      {"update": {}, "feedSession": True}, {"update": {}, "epoch": True},
                      {"update": {}, "message": "capture-identity-or-epoch-changed"}, {"update": {}, "source": True}):
            with self.subTest(extra=extra):
                self.run_ui("retained-boundary", **extra)

    def test_retained_exact_five_second_lease_expires_without_becoming_current_again(self):
        self.retained_session()
        partial = self.snapshot["partial_observation"]
        now = self.snapshot["capture"]["last_heartbeat_unix_ms"]
        partial.update(captured_at_unix_ms=now, expires_at_unix_ms=now + 5000, remaining_ms=5000)
        self.run_ui("retained-five-second-lease")

    def test_retained_capture_epoch_fences_old_tickets_during_absent_observations(self):
        self.retained_session()
        self.run_ui("retained-epoch-fence")

    def test_retained_stop_source_loss_errors_and_disabled_inference_clear(self):
        self.retained_session()
        updates = [{"capture_session": {"status": state}} for state in ("idle", "stopped", "failed", "interrupted")]
        updates += [{"server": {"model_state": state}} for state in ("disabled", "loading", "failed")]
        updates += [{"capture": {"state": state, "fresh_capture": False}} for state in ("unavailable", "disconnected", "blocked")]
        updates += [{"server": {"inference_enabled": False}}, {"capture_session": {"inference_enabled": False}},
                    {"capture_session": {"mode": "capture-only"}}, {"capture_session": {"remaining_ms": 0}},
                    {"capture_session": {"recorded_frames": 1200}},
                    {"automatic_startup": {"enabled": True, "status": "failed", "stop_reason": "automatic-startup-failed"}}]
        for update in updates:
            with self.subTest(update=update):
                self.run_ui("retained-boundary", update=update)
        for message in ("source-unavailable", "source-changed", "capture-failed", "inference-failed",
                        "publication-failed", "feed-failed", "recorder-failure"):
            with self.subTest(message=message):
                self.run_ui("retained-boundary", update={}, message=message)

    def test_retained_transient_freshness_and_heartbeat_loss_never_claim_current_data(self):
        self.retained_session()
        self.run_ui("retained-transient")

    def test_retained_api_admitted_numbers_survive_transient_unavailable_only_as_stale_display(self):
        self.retained_session()
        self.snapshot["capture"].update(state="unavailable", fresh_capture=False)
        for message in ("capture-not-fresh", "capture-heartbeat-expired"):
            with self.subTest(message=message):
                self.snapshot["message"] = message
                self.run_ui("retained-unavailable-admitted")
        self.snapshot["capture"]["epoch"] = None
        self.run_ui("retained-empty")

    def test_retained_existing_numbers_survive_only_closed_transient_unavailable_reasons_with_recent_owner(self):
        self.retained_session()
        for reason in ("capture-not-fresh", "capture-heartbeat-expired"):
            with self.subTest(reason=reason):
                self.run_ui("retained-unavailable", reason=reason)

    def test_retained_cache_requires_explicit_per_field_acceptance_never_unsupported_numeric_assertions(self):
        self.retained_session()
        partial = self.snapshot["partial_observation"]
        partial["field_statuses"] = {"seats.4.displayed_stack": {"status": "accepted", "reason": None}}
        self.run_ui("retained-accepted-only")
        partial["field_statuses"] = {}
        self.run_ui("retained-accepted-only", none=True)

    def test_retained_cache_requires_public_epoch_geometry_and_service_binding(self):
        self.retained_session()
        for field in ("epoch", "width", "height", "instance_id"):
            with self.subTest(field=field):
                owner = self.snapshot["server" if field == "instance_id" else "capture"]
                value = owner.pop(field)
                self.run_ui("retained-accepted-only", none=True)
                owner[field] = value

    def test_retained_unsafe_advice_schema_and_disconnect_clear_without_storage_revival(self):
        self.retained_session()
        for unsafe in ({"schema_version": 2}, {"capture_session": "PRIVATE"},
                       {"server": {"model_state": "ready", "advice_ready": True, "quality_gate": "approved"}}):
            with self.subTest(unsafe=unsafe):
                self.run_ui("retained-unsafe", unsafe=unsafe)
        self.run_ui("retained-disconnect")

    def test_retained_refresh_starts_empty_for_missing_or_expired_fields_and_only_polls_state_get(self):
        self.retained_session()
        self.run_ui("polling")
        partial = self.snapshot["partial_observation"]
        partial.update(remaining_ms=0, expires_at_unix_ms=self.snapshot["capture"]["last_heartbeat_unix_ms"] - 1)
        self.run_ui("retained-empty")
        self.snapshot["partial_observation"] = None
        self.run_ui("retained-empty")

    def test_literal_amounts_reasons_and_zero_without_currency_invention(self):
        value = self.snapshot["partial_observation"]
        value["pot_size_text"] = "123.45"
        value["seats"][0]["displayed_stack_text"] = "1.0"
        value["seats"][3]["displayed_stack_text"] = "$0.00"
        value["field_statuses"]["seats.3.displayed_stack"] = {"status": "unavailable", "reason": "occluded"}
        value["field_statuses"]["PRIVATE"] = {"status": "unavailable", "reason": "PRIVATE"}
        self.run_ui("literal")

    def test_capture_only_budget_loss_deficit_and_stale_receipt(self):
        self.snapshot["server"].update(inference_enabled=True, model_state="ready", inference_busy=True)
        self.snapshot["capture_session"] = {
            "session_id": "manual-session-a",
            "mode": "capture-only", "status": "capturing", "inference_enabled": False,
            "elapsed_ms": 1000, "max_duration_ms": 600000, "remaining_ms": 599000, "max_frames": 1200,
            "recorded_frames": 2, "capture_failures": 1, "gap_count": 1,
            "max_gap_ms": 2000, "estimated_missed_samples": 3,
            "distinct_opportunities": 2, "target_opportunities": 20, "opportunity_deficit": 18,
            "updated_at_unix_ms": self.snapshot["capture"]["last_heartbeat_unix_ms"],
        }
        self.run_ui("recording")

    def test_idle_session_distinguishes_service_opt_in_and_model_loading(self):
        self.manual_session(mode="capture-only", status="idle", updated_at_unix_ms=None)
        for model in ("disabled", "loading", "ready", "failed"):
            with self.subTest(model=model):
                self.snapshot["server"].update(model_state=model, inference_enabled=model != "disabled")
                self.run_ui("manual-blocked", expected={
                    "source-status": "No manual session", "recorder-status": "No manual session",
                    "inference-status": "model loading" if model == "loading" else "Inference OFF",
                    "model-status": model, "monitor-empty": "No manual session",
                })

    def test_manual_inference_without_result_is_not_admitted_or_busy_by_default(self):
        self.manual_session()
        self.snapshot["partial_observation"] = None
        self.snapshot["field_statuses"]["pot_size"] = {"status": "unavailable", "reason": "below-floor"}
        for busy in (False, True):
            self.snapshot["server"]["inference_busy"] = busy
            with self.subTest(busy=busy):
                self.run_ui("manual-empty", expected={
                    "inference-status": "Inference enabled / no admissible result",
                    "model-status": " / busy" if busy else " / idle",
                })

    def test_empty_partial_does_not_claim_an_admissible_result(self):
        self.manual_session()
        partial = self.snapshot["partial_observation"]
        partial.update(game_phase=None, board_count=None, board_slots=[None] * 5, pot_size=None,
                       seats=[{"seat": seat, "displayed_stack": None} for seat in range(1, 7)])
        partial["field_statuses"]["pot_size"] = {"status": "unavailable", "reason": "below-floor"}
        self.run_ui("manual-empty", expected={"inference-status": "no admissible result"})

    def test_partial_inference_keeps_independent_values_and_specific_rejections(self):
        self.manual_session()
        partial = self.snapshot["partial_observation"]
        partial.update(game_phase="preflop", board_count=0, pot_size_text="123.45")
        partial["field_statuses"]["board_slots.2"] = {"status": "unavailable", "reason": "below-floor"}
        partial["field_statuses"]["seats.3.displayed_stack"] = {"status": "unavailable", "reason": "occluded"}
        for busy in (False, True):
            self.snapshot["server"]["inference_busy"] = busy
            with self.subTest(busy=busy):
                self.run_ui("manual-partial", expected={"inference-status": "Inference enabled / partial result"})

    def test_board_transitions_to_empty_and_unreadable_do_not_retain_prior_cards_with_unknown_role(self):
        self.manual_session()
        self.run_ui("board-transitions")

    def test_terminal_receipts_clear_fresh_results_and_reject_newer_tickets(self):
        self.manual_session()
        for status, reason in (("stopped", "operator-stop"), ("failed", "inference-failed"),
                               ("interrupted", "publication-failed"), ("failed", "model-not-ready"),
                               ("failed", "feed-failed")):
            with self.subTest(status=status):
                self.run_ui("manual-invalidation", update={"capture_session": {"status": status, "stop_reason": reason}},
                            stopReason=reason)

    def test_readiness_and_consent_never_imply_each_other(self):
        self.manual_session()
        for update in ({"server": {"model_state": "failed"}}, {"server": {"model_state": "loading"}},
                       {"server": {"model_state": "disabled"}}, {"server": {"inference_enabled": False}},
                       {"capture_session": {"inference_enabled": False}},
                       {"capture_session": {"mode": "capture-only"}},
                       {"capture_session": {"status": "idle"}},
                       {"capture": {"state": "unavailable", "fresh_capture": False}}):
            with self.subTest(update=update):
                self.run_ui("manual-invalidation", update=update)

    def test_active_inference_receipt_expiry_clears_still_fresh_result(self):
        self.manual_session(updated_at_unix_ms=self.snapshot["capture"]["last_heartbeat_unix_ms"] - 4500)
        self.run_ui("manual-receipt-expiry")

    def test_manual_observation_lease_expiry_and_disconnect_clear_status_and_values(self):
        self.manual_session()
        self.run_ui("manual-lease-expiry")
        self.run_ui("manual-disconnect")

    def test_unknown_and_future_receipt_times_do_not_admit_readings(self):
        for timestamp in (None, 0, self.snapshot["capture"]["last_heartbeat_unix_ms"] + 501):
            with self.subTest(timestamp=timestamp):
                self.manual_session(updated_at_unix_ms=timestamp)
                self.run_ui("manual-blocked", expected={"recorder-status": "status stale"})

    def test_malformed_session_cannot_fall_back_to_legacy_feed_admission(self):
        self.manual_session()
        valid = self.snapshot["capture_session"]
        invalid = [{}, "PRIVATE", [], {**valid, "mode": "PRIVATE"},
                   {**valid, "status": "waiting-model"}, {**valid, "inference_enabled": "true"},
                   {key: value for key, value in valid.items() if key != "inference_enabled"}]
        self.run_ui("manual-malformed", invalid=invalid)

    def test_historical_feed_without_manual_receipt_still_renders(self):
        self.snapshot.pop("capture_session", None)
        self.run_ui("legacy")
        self.snapshot["capture_session"] = None
        self.run_ui("legacy")

    def test_only_state_get_is_polled_and_at_most_one_request_survives_resume(self):
        self.manual_session()
        self.run_ui("polling")

    def test_manual_budget_expires_on_both_clocks_and_cannot_rearm(self):
        self.manual_session(elapsed_ms=990, max_duration_ms=1000, remaining_ms=10)
        for clock in ("normal", "forward", "backward"):
            with self.subTest(clock=clock):
                self.run_ui("manual-budget-timeout", clock=clock)

    def test_manual_budget_cannot_be_extended_by_repeated_poll_or_resume(self):
        self.manual_session(elapsed_ms=990, max_duration_ms=1000, remaining_ms=10)
        for reconnect in (False, True):
            with self.subTest(reconnect=reconnect):
                self.run_ui("manual-budget-no-renewal", reconnect=reconnect)

    def test_manual_budget_can_only_shorten_and_accounts_for_request_time(self):
        self.manual_session(elapsed_ms=900, max_duration_ms=1000, remaining_ms=100)
        self.run_ui("manual-budget-shorten", advance=11)
        self.run_ui("manual-budget-shorten", roundTrip=20, advance=81)

    def test_frame_limit_is_frozen_and_exhaustion_cannot_be_undone(self):
        self.manual_session(max_frames=3, recorded_frames=2)
        self.run_ui("manual-frame-budget")

    def test_missing_or_exhausted_manual_budgets_never_admit(self):
        for fields in ({"remaining_ms": 0}, {"elapsed_ms": 600000}, {"max_duration_ms": 0},
                       {"recorded_frames": 1200}, {"max_frames": 0}, {"remaining_ms": None},
                       {"max_duration_ms": None}, {"elapsed_ms": None}, {"max_frames": None},
                       {"recorded_frames": None}, {"session_id": None}):
            with self.subTest(fields=fields):
                self.manual_session(**fields)
                self.run_ui("manual-blocked", expected={"inference-status": "budget closed"})

    def test_replacing_manual_session_clears_old_reading_and_retires_old_id(self):
        self.manual_session()
        self.run_ui("manual-session-replaced")

    def test_stopped_or_missing_manual_session_cannot_revive_through_new_feed(self):
        self.manual_session()
        for absent in (False, True):
            with self.subTest(absent=absent):
                self.run_ui("manual-session-closed", absent=absent)

    def test_automatic_startup_is_metadata_only_without_a_capture_session(self):
        self.snapshot.pop("capture_session", None)
        self.snapshot["server"].update(inference_enabled=True, model_state="ready")
        for status, label in (("waiting-model", "Waiting for model"), ("searching", "Searching for table"),
                              ("verifying", "Verifying table activity"), ("active", "Waiting for table receipt"),
                              ("stopped", "Automatic observation stopped"), ("failed", "Automatic observation failed"),
                              ("idle", "Automatic observation idle"), ("interrupted", "Automatic observation interrupted")):
            with self.subTest(status=status):
                self.snapshot["server"]["model_state"] = "loading" if status == "waiting-model" else "ready"
                self.snapshot["automatic_startup"] = {"enabled": True, "status": status, "stop_reason": None}
                self.run_ui("manual-blocked", expected={"source-status": label, "monitor-empty": label,
                                                        "recorder-stop": "never starts capture or inference"})

    def test_automatic_startup_search_does_not_reuse_previous_stopped_receipt(self):
        self.manual_session(status="stopped")
        self.snapshot["automatic_startup"] = {"enabled": True, "status": "searching", "stop_reason": None}
        self.run_ui("manual-blocked", expected={"source-status": "Searching for table", "monitor-empty": "Metadata only"})

    def test_automatic_readout_needs_verifying_or_active_source_without_assuming_hero_role(self):
        for activity, label in (("searching", "Searching for table"), ("verifying", "Source capturing / verifying table activity"),
                                ("idle", "Automatic observation idle"), (None, "Automatic observation idle"),
                                ("active", "Observing active table")):
            with self.subTest(activity=activity):
                self.manual_session(source_policy="automatic-bounded")
                if activity is not None:
                    self.snapshot["capture_session"]["activity_state"] = activity
                self.run_ui("automatic-active" if activity == "active" else "automatic-preactivity" if activity == "verifying" else "manual-blocked",
                            expected={"source-status": label, "recorder-status": "Automatic inference"})

    def test_source_start_and_activity_transitions_preserve_partial_until_stop(self):
        self.manual_session(source_policy="automatic-bounded", activity_state="verifying")
        self.snapshot["capture"].update(state="verifying", fresh_capture=False)
        self.run_ui("automatic-transition")

    def test_preactivity_ui_hides_hero_scene_and_history_but_keeps_independent_fields(self):
        self.manual_session(source_policy="automatic-bounded", activity_state="verifying")
        self.snapshot["partial_observation"].update(role="observing", hero_seated=False)
        self.snapshot["partial_observation"]["seats"][0].update(acting=True, occupied=True,
                                                                   scene_fields=["acting", "occupied"])
        self.snapshot["history"] = {"state": "partial", "counts": {"folds": 2}, "gaps": 3,
                                    "events": [{"kind": "action", "action": "fold", "seat": 2}]}
        self.run_ui("automatic-preactivity")

    def test_preactivity_full_observation_is_not_a_partial_readout(self):
        now = self.snapshot["capture"]["last_heartbeat_unix_ms"]
        self.snapshot["partial_observation"] = None
        self.snapshot["observation"] = {
            "generation": 1, "epoch": 1, "captured_at_unix_ms": now - 500,
            "expires_at_unix_ms": now + 1000, "remaining_ms": 1000, "experimental": True,
            "role": "uncertain", "hero_seated": True, "hero_seat": 2,
            "hero_cards": [], "board": [], "game_phase": "preflop", "controls": [], "wagers": [],
            "amounts": {"pot_size": 12345, "hero_chips": 2145},
        }
        self.manual_session(source_policy="automatic-bounded", activity_state="verifying")
        self.run_ui("manual-blocked")

    def test_terminal_automatic_receipt_preserves_already_qualified_saved_history(self):
        self.manual_session(status="stopped", source_policy="automatic-bounded", activity_state="idle")
        self.snapshot["history"] = {"state": "partial", "counts": {"folds": 2}, "gaps": 1,
                                    "events": [{"kind": "action", "action": "fold", "seat": 2}]}
        self.run_ui("saved-qualified-history")

    def test_preactivity_readout_expiry_source_loss_stop_and_budget_remain_fail_closed(self):
        self.manual_session(source_policy="automatic-bounded", activity_state="verifying")
        for capture_state in ("active", "verifying"):
            with self.subTest(capture_state=capture_state):
                self.snapshot["capture"]["state"] = capture_state
                self.run_ui("automatic-preactivity")
                self.run_ui("manual-lease-expiry")
                self.run_ui("manual-disconnect")
                self.run_ui("manual-invalidation", update={"capture": {"state": "unavailable", "fresh_capture": False}})
                self.run_ui("manual-invalidation", update={"capture_session": {"status": "stopped", "stop_reason": "operator-stop"}})
        self.manual_session(source_policy="automatic-bounded", activity_state="verifying", elapsed_ms=990,
                            max_duration_ms=1000, remaining_ms=10)
        self.run_ui("manual-budget-no-renewal", reconnect=True)
        self.run_ui("manual-budget-timeout", clock="backward")

    def test_automatic_capture_only_and_stopped_startup_never_admit(self):
        self.manual_session(mode="capture-only", source_policy="automatic-bounded", activity_state="active")
        self.run_ui("manual-blocked", expected={"inference-status": "Inference OFF"})
        self.manual_session(source_policy="automatic-bounded", activity_state="active")
        for status in ("waiting-model", "searching", "stopped", "failed", "interrupted", "idle"):
            with self.subTest(status=status):
                self.snapshot["automatic_startup"] = {"enabled": True, "status": status, "stop_reason": None}
                self.run_ui("manual-blocked")
        self.snapshot.pop("automatic_startup")
        self.run_ui("automatic-startup-terminal")

    def test_explicit_manual_session_remains_independent_of_automatic_startup(self):
        self.manual_session(source_policy="manual", activity_state="active")
        self.snapshot["automatic_startup"] = {"enabled": True, "status": "searching", "stop_reason": None}
        self.run_ui("legacy", expected={"source-status": "Source connected", "recorder-status": "Diagnostic inference"})

    def test_automatic_policy_keeps_original_budget_and_read_only_polling(self):
        self.manual_session(source_policy="automatic-bounded", activity_state="active", elapsed_ms=990,
                            max_duration_ms=1000, remaining_ms=10)
        self.run_ui("manual-budget-no-renewal", reconnect=True)
        self.run_ui("manual-budget-timeout", clock="backward")
        self.manual_session(source_policy="automatic-bounded", activity_state="active", max_frames=3, recorded_frames=2)
        self.run_ui("manual-frame-budget")
        self.snapshot["capture_session"] = None
        self.snapshot["automatic_startup"] = {"enabled": True, "status": "searching", "stop_reason": None}
        self.run_ui("polling")

    def test_unknown_automatic_metadata_is_rejected_not_promoted_to_manual(self):
        self.manual_session(source_policy="manual", activity_state="active")
        receipt = self.snapshot["capture_session"]
        invalid = [{"capture_session": {**receipt, "source_policy": policy}} for policy in ("PRIVATE", None)]
        invalid += [{"capture_session": {**receipt, "activity_state": activity}} for activity in ("PRIVATE", None)]
        invalid += [{"automatic_startup": startup} for startup in ({}, "PRIVATE",
                    {"enabled": "true", "status": "searching"}, {"enabled": True, "status": "PRIVATE"})]
        self.run_ui("automatic-malformed", invalid=invalid)

    def test_topic_selection_and_search_preserve_educational_content(self):
        self.run_ui("reference-select")

    def test_phase_contradiction_does_not_clear_independent_card_identities(self):
        self.snapshot["partial_observation"].update(game_phase="preflop", board_count=0)
        self.run_ui("phase-independent")

    def test_uncertain_turn_preserves_explicit_hero_stack_not_guessed_seat_four(self):
        now = self.snapshot["capture"]["last_heartbeat_unix_ms"]
        self.snapshot["partial_observation"] = None
        self.snapshot["observation"] = {
            "generation": 1, "epoch": 1, "captured_at_unix_ms": now - 500,
            "expires_at_unix_ms": now + 1000, "remaining_ms": 1000,
            "role": "uncertain", "hero_seated": True, "hero_seat": 2, "action_required": None,
            "hero_cards": [], "board": [], "game_phase": "preflop", "controls": [], "wagers": [],
            "amounts": {"pot_size": 12345, "hero_chips": 2145, "to_call": 500},
            "amount_texts": {"hero_chips": "21.45"}, "experimental": True,
        }
        self.run_ui("hero-independent")

    def context_session(self):
        self.retained_session()
        self.snapshot["capture"]["source_id"] = "0123456789abcdef"
        now = self.snapshot["capture"]["last_heartbeat_unix_ms"]
        capture = {"service_instance_id": "service-a", "session_id": self.snapshot["session_id"],
                   "capture_session_id": self.snapshot["capture_session"]["session_id"],
                   "source_id": self.snapshot["capture"]["source_id"], "epoch": self.snapshot["capture"]["epoch"],
                   "sequence": 10, "captured_at_ms": 10000, "captured_at_unix_ms": now - 500,
                   "sha256": "f" * 64, "width": self.snapshot["capture"]["width"], "height": self.snapshot["capture"]["height"]}
        original = {**capture, "sequence": 3, "captured_at_ms": 3000, "captured_at_unix_ms": now - 60500,
                    "sha256": "e" * 64}
        stats = {"source": "client_profile_tooltip", "owner": "Player 1", "seat": 1, "occupant_epoch": 1,
                 "metrics": {"vpip": {"label": "VPIP", "literal": "12.5%", "percent": 12.5, "status": "accepted"},
                             "pfr": {"label": "PFR", "literal": "0%", "percent": 0, "status": "accepted"},
                             "three_bet": {"label": "3-BET", "literal": "-", "percent": None, "status": "dash"},
                             "c_bet": {"label": "Flop C-BET", "literal": None, "percent": None, "status": "missing"}},
                 "sample_size": None, "scope": None, "capture": original,
                 "captured_at_unix_ms": original["captured_at_unix_ms"], "evidence_id": "e" * 64,
                 "status": "last_observed", "table_context_id": "table-a"}
        self.snapshot["table_context"] = {"schema_version": 1, "capture": capture, "expires_at_unix_ms": now + 4500,
            "role": "observing", "hero_seat": None, "table_context_id": "table-a",
            "seats": [{"seat": seat, "occupancy": "occupied", "identity": f"Player {seat}", "occupant_epoch": 1,
                       "continuity": "confirmed", "status": "confirmed", "reason": "Source-bound fixture",
                       "stats": copy.deepcopy(stats) if seat == 1 else None} for seat in range(1, 7)],
            "evidence": {"role": {"status": "confirmed", "origin": "observer_controls", "hero_seat": None,
                                  "capture": copy.deepcopy(capture)}}, "occluded_regions": [], "events": []}
        self.snapshot["history"] = {"state": "partial", "counts": {"folds": 2}, "gaps": 1,
                                    "events": [{"kind": "action", "action": "fold", "seat": 2}]}
        self.snapshot["capture_session"]["activity_state"] = "active"
        return self.snapshot["table_context"]

    def test_persistent_six_unknown_slots_and_five_cards_survive_loss_without_poll_churn(self):
        self.manual_session()
        self.run_ui("persistent-table")

    def test_source_bound_selected_profile_literals_unknowns_focus_and_original_time(self):
        self.context_session()
        self.run_ui("context-render")

    def test_context_roles_all_six_hero_seats_do_not_promote_advice_or_reset_local_history(self):
        context = self.context_session()
        self.snapshot["partial_observation"] = None
        for role, label, origin in (("seated_waiting", "Seated / waiting", "self_player"),
                                    ("your_turn", "Your turn", "own_action_controls")):
            for seat in range(1, 7):
                with self.subTest(role=role, seat=seat):
                    context.update(role=role, hero_seat=seat)
                    context["evidence"]["role"].update(origin=origin, hero_seat=seat)
                    self.run_ui("context-role", roleLabel=label, hero=seat)
        context["evidence"]["role"]["origin"] = "opponent_showdown"
        self.run_ui("context-role", roleLabel="Uncertain", hero=None)

    def test_context_lease_expiry_and_same_ticket_rewrites_do_not_renew_identity_or_stats(self):
        self.context_session()
        self.run_ui("context-expiry")

    def test_uncertain_refresh_keeps_last_seen_name_without_rebinding_stats_or_timestamp(self):
        self.context_session()
        self.run_ui("context-name-continuity")

    def test_occupied_unreadable_name_is_distinct_from_empty_and_uncertain_seat(self):
        self.context_session()
        for index, occupancy in enumerate(("occupied", "empty", "unknown")):
            self.snapshot["table_context"]["seats"][index].update(identity=None, occupancy=occupancy,
                continuity="uncertain", status="unknown" if occupancy == "unknown" else "provisional", stats=None)
        self.run_ui("context-pending-labels")

    def test_replacement_vacancy_and_same_window_table_boundary_detach_old_attachments(self):
        self.context_session()
        self.run_ui("context-replacement")
        self.run_ui("context-table-boundary")

    def test_context_scope_service_source_geometry_and_capture_forgery_fail_unknown(self):
        self.context_session()
        baseline = copy.deepcopy(self.snapshot)
        for key, value in (("source_id", "1" * 16), ("service_instance_id", "other-service"),
                           ("session_id", "other-feed"), ("capture_session_id", "other-owner"),
                           ("epoch", 2), ("width", baseline["capture"]["width"] + 1),
                           ("captured_at_unix_ms", baseline["capture"]["last_heartbeat_unix_ms"] + 1),
                           ("sha256", "bad-hash")):
            with self.subTest(key=key):
                self.snapshot = copy.deepcopy(baseline)
                self.snapshot["table_context"]["capture"][key] = value
                self.run_ui("context-reject")

    def test_last_observed_profiles_require_atomic_current_owner_and_original_scope(self):
        self.context_session()
        baseline = copy.deepcopy(self.snapshot)
        for key, value in (("owner", "Player 2"), ("seat", 2), ("occupant_epoch", 2),
                           ("table_context_id", "other-table"), ("source", "local_history"),
                           ("captured_at_unix_ms", baseline["capture"]["last_heartbeat_unix_ms"])):
            with self.subTest(key=key):
                self.snapshot = copy.deepcopy(baseline)
                self.snapshot["table_context"]["seats"][0]["stats"][key] = value
                self.run_ui("context-stats-reject")
        for key, value in (("source_id", "1" * 16), ("service_instance_id", "other-service"),
                           ("epoch", 2), ("sequence", 11), ("width", baseline["capture"]["width"] + 1)):
            with self.subTest(capture_key=key):
                self.snapshot = copy.deepcopy(baseline)
                self.snapshot["table_context"]["seats"][0]["stats"]["capture"][key] = value
                self.run_ui("context-stats-reject")

    def test_duplicate_uncertain_and_occluded_identity_detach_profiles_without_false_vacancy(self):
        context = self.context_session()
        context["seats"][0]["continuity"] = "uncertain"
        self.run_ui("context-uncertain-owner", occupancy="6/6 seats occupied")
        context["seats"][0]["continuity"] = "confirmed"
        context["seats"][1]["identity"] = "Player 1"
        self.run_ui("context-uncertain-owner", occupancy="6/6 seats occupied")
        context["seats"][0].update(occupancy="unknown", status="unknown", reason="Occluded")
        self.run_ui("context-uncertain-owner")

    def test_render_receipts_keep_distinct_exact_lane_originals_and_publication_clocks(self):
        context = self.context_session()
        original = {**context["capture"], "sequence": 9, "sha256": "a" * 64}
        self.snapshot["partial_observation"]["capture"] = original
        self.run_ui("context-receipts")

    def test_separate_popup_stats_keep_child_original_and_validate_parent_table_crosswalk(self):
        self.context_session()
        stats = self.snapshot["table_context"]["seats"][0]["stats"]
        original = stats["capture"]
        stats["capture"] = {**original, "width": 260, "height": 180, "sha256": "c" * 64,
                            "parent_capture": copy.deepcopy(original), "popup_index": 0, "non_atomic": True,
                            "popup_window": {"hwnd": "0x111", "owner_hwnd": "0x222", "root_owner_hwnd": "0x222",
                                             "process_id": 123, "window_class": "ProfileFixture"}}
        self.run_ui("context-popup")
        baseline = copy.deepcopy(self.snapshot)
        for key, value in (("source_id", "1" * 16), ("epoch", 2), ("width", original["width"] + 1)):
            with self.subTest(parent_key=key):
                self.snapshot = copy.deepcopy(baseline)
                self.snapshot["table_context"]["seats"][0]["stats"]["capture"]["parent_capture"][key] = value
                self.run_ui("context-stats-reject")
        self.snapshot = copy.deepcopy(baseline)
        self.snapshot["table_context"]["seats"][0]["stats"]["capture"]["non_atomic"] = False
        self.run_ui("context-stats-reject")

    def test_profile_unknown_missing_locale_range_and_wrong_labels_are_atomic_not_local_rates(self):
        context = self.context_session()
        stats = context["seats"][0]["stats"]
        stats["metrics"]["vpip"].update(literal="12,5%", percent=12.5, status="invalid")
        stats["metrics"]["pfr"].update(literal="101%", percent=101, status="invalid")
        stats["metrics"]["three_bet"].update(label="VPIP", literal="5%", percent=5, status="accepted")
        stats["metrics"].pop("c_bet")
        stats["evidence_id"] = "https://untrusted.invalid/profile"
        self.run_ui("context-metric-validation", metricValues=["-"] * 4,
                    metricStates=["invalid", "invalid", "unknown", "missing"], noEvidence=True)

    def test_render_journal_is_bounded_and_reports_drops_without_renewing_sources(self):
        self.manual_session()
        self.run_ui("context-receipt-cap")

    def test_last_seen_pot_and_stacks_do_not_clear_and_repaint_on_each_clock_refresh(self):
        self.retained_session()
        self.run_ui("context-calm-retained")

    def test_unknown_caption_does_not_invent_a_new_table_or_permanently_retire_the_current_one(self):
        self.context_session()
        self.run_ui("context-caption-unknown")

    def test_profile_coarse_age_does_not_move_backwards_with_browser_wall_clock(self):
        context = self.context_session()
        stats = context["seats"][0]["stats"]
        captured = self.snapshot["capture"]["last_heartbeat_unix_ms"] - 60001
        stats["capture"]["captured_at_unix_ms"] = stats["captured_at_unix_ms"] = captured
        self.run_ui("context-source-clock")

    def test_new_atomic_profile_does_not_fill_missing_metrics_from_previous_profile(self):
        self.context_session()
        self.run_ui("context-atomic-missing")


if __name__ == "__main__":
    unittest.main()
