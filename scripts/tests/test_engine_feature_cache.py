"""Exact feature-cache tests; GPU proof is opt-in and refuses a running service."""

import hashlib
import json
import os
from pathlib import Path
import socket
import statistics
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_laya_server as fixtures

srv = fixtures.srv


def uncached_predict_many(self, samples):
    """Frozen pre-cache Engine.predict_many (2026-10-13), independent of cache helpers."""
    if not samples:
        return []
    if any(len(questions) > self.batch_size for _, _, questions in samples):
        return [self.predict(images, note, questions) for images, note, questions in samples]
    import numpy as np
    import torch
    from laya import vlm

    agent = self.agent
    if self.calibration is not None:
        self.calibration.check(vlm.checkpoint_identity(agent))
    temperatures = vlm.resolve_temperature(None, self.calibration)
    definitions, scored_batches = [], []
    text_rows = {}
    with torch.inference_mode():
        prefixes = self._prefixes(samples)
        for sample_index, ((images, note, questions), prefix) in enumerate(zip(samples, prefixes)):
            rows = []
            for qid, question in questions.items():
                if question["type"] not in ("choice", "noul"):
                    raise ValueError("batch-question-invalid")
                internal = agent._to_internal(question)
                options = len(vlm.render_options(internal))
                key = (note, tuple(prefix["ids"]), prefix["n_images"],
                       json.dumps(internal, ensure_ascii=True, separators=(",", ":")))
                if key not in text_rows:
                    text_prefix = {**prefix, "pixel_values": None,
                                   "pixel_attention_mask": None, "raw_images": None}
                    item = vlm.build_vlm_inputs(agent.processor, {"note": note}, internal,
                        agent.cfg.get("max_len", 1024), agent.cfg.get("head_max_len", 256), prefix=text_prefix)
                    if len(item["markers"]) != options:
                        raise ValueError("batch-question-invalid")
                    item["qtype"] = vlm.QTYPES[internal["t"]]
                    text_rows[key] = item
                item = text_rows[key]
                rows.append({**item, "sample_index": sample_index})
                definitions.append((sample_index, qid, internal,
                                     vlm.truncation_answer(item["truncation"], internal)))
            image_features = None
            if images and prefix["raw_images"] is not None:
                image_features = agent.model.encode_raw_images(prefix["raw_images"])
            elif images:
                image_features = agent.model.encode_images(
                    prefix["pixel_values"].to(agent.device, agent._torch_dtype()),
                    prefix["pixel_attention_mask"].to(agent.device))
            for offset in range(0, len(rows), self.batch_size):
                chunk = rows[offset:offset+self.batch_size]
                batch = vlm.collate_vlm(chunk, agent.processor.tokenizer.pad_token_id, with_pixels=False)
                features = image_features.repeat(len(chunk), 1, 1) if image_features is not None else None
                args = [batch[k].to(agent.device) for k in
                        ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")]
                scored, _ = agent.model(*args, image_hidden_states=features,
                                       option_span=batch["option_span"].to(agent.device))
                scored_batches.append(scored)
        logits = [row for scored in scored_batches for row in scored.float().cpu().numpy()]
        torch.cuda.synchronize()
    output = [{"answers": {}} for _ in samples]
    for (sample_index, qid, question, truncated), scored in zip(definitions, logits):
        count = len(vlm.render_options(question))
        scale = temperatures.get(vlm.QTYPES[question["t"]],
                                 agent._checkpoint_temperature(vlm.QTYPES[question["t"]], count))
        z = np.asarray(scored[:count], dtype=np.float64) / max(1e-3, float(scale))
        probabilities = np.exp(z-z.max())
        probabilities /= probabilities.sum()
        if question["t"] == "choice":
            options = list(question["crit"])
            answer = {"type": "choice", "choice": options[int(probabilities.argmax())],
                      "probabilities": {key: round(float(p), 4) for key, p in zip(options, probabilities)},
                      "confidence": round(vlm.confidence_from_probs(probabilities, count), 4)}
        else:
            value = float(probabilities[1])
            answer = {"type": "noul", "noul": round(value, 4),
                      "confidence": round(max(value, 1.0-value), 4)}
        if truncated:
            answer["truncated"] = truncated
        output[sample_index]["answers"][qid] = answer
    return output


class RGB(int):
    mode = "RGB"

    def __new__(cls, value, size=(2, 2), pixels=None):
        image = int.__new__(cls, value)
        image.size = size
        image.width, image.height = size
        image.pixels = bytes([value % 256]) * (size[0]*size[1]*3) if pixels is None else pixels
        return image

    def tobytes(self):
        return self.pixels


class FeatureCacheTests(unittest.TestCase):
    def setUp(self):
        self.fake = fixtures.EngineBatchTests()
        self.fake.setUp()
        self.addCleanup(self.fake.doCleanups)
        self.engine = self.fake.engine
        self.engine.agent.model.training = False
        self.engine._image_feature_cache = {}
        self.engine._image_feature_cache_bytes = 0
        self.engine._image_feature_cache_limit = 16 * 1024 * 1024
        self.engine._image_feature_cache_context = None
        tensor = type(self.fake.torch.cat([]))
        tensor.numel = lambda value: len(value) * 64 * 576
        tensor.element_size = lambda value: 2
        tensor.detach = lambda value: value
        tensor.clone = lambda value: tensor(value)
        self.questions = {"g1": {"type": "choice", "instructions": "character", "criteria": ["1", "2", "3"]}}

    def sample(self, images, note="digits", questions=None):
        return (images, note, self.questions if questions is None else questions)

    def check(self, samples):
        self.assertEqual(self.engine.predict_many(samples), self.fake.reference(samples))

    def test_exact_pixels_reuse_only_features_and_prefix_not_questions_or_answers(self):
        self.check([self.sample([RGB(7), RGB(11)])])
        changed = {"fresh": {"type": "choice", "instructions": "truncate", "criteria": ["3", "2", "1"]},
                   "visible": {"type": "noul", "instructions": "visible now"}}
        sample = self.sample([RGB(7), RGB(11)], note="fresh source note", questions=changed)
        before = self.engine.predict_many([sample])
        self.assertEqual(before, self.fake.reference([sample]))
        before[0]["answers"].clear()
        self.check([sample])
        self.assertEqual(self.fake.encoded, [[7, 11]])
        self.assertEqual(len(self.fake.preprocessed), 1)
        self.assertEqual(len(self.fake.forwarded), 3)
        self.assertEqual(self.engine.calibration.check.call_count, 3)
        self.assertEqual(len(self.fake.built), 5)
        prefix, features, _ = next(iter(self.engine._image_feature_cache.values()))
        self.assertEqual(features, [7, 11])
        self.assertIsNone(prefix["pixel_values"])
        self.assertIsNone(prefix["pixel_attention_mask"])
        self.assertIsNone(prefix["raw_images"])

    def test_one_pixel_dimension_order_and_state_count_changes_are_misses(self):
        states = [[RGB(7), RGB(11)], [RGB(7), RGB(11, pixels=b"x" + bytes([11])*11)],
                  [RGB(7, size=(1, 4)), RGB(11)], [RGB(11), RGB(7)], [RGB(7)]]
        for images in states:
            self.check([self.sample(images)])
        self.assertEqual(len(self.fake.encoded), 5)
        self.assertEqual(self.fake.encoded[0], [7, 11])
        self.assertEqual(self.fake.encoded[-1], [7])
        self.assertEqual(len(self.engine._image_feature_cache), 5)

    def test_duplicate_states_within_call_keep_full_encoder_and_text_shapes(self):
        samples = [self.sample([RGB(7), RGB(11)]), self.sample([RGB(7), RGB(11)], note="another seat")]
        self.check(samples)
        self.assertEqual(self.fake.encoded, [[7, 11]])
        self.assertEqual(self.fake.forwarded, [[[7, 11]], [[7, 11]]])

    def test_lru_and_byte_budget_are_bounded(self):
        self.check([self.sample([RGB(1)])])
        size = self.engine._image_feature_cache_bytes
        self.engine._image_feature_cache_limit = size * 2
        for value in (2, 1, 3, 1, 2):
            self.check([self.sample([RGB(value)])])
            self.assertLessEqual(self.engine._image_feature_cache_bytes, size*2)
        self.assertEqual(self.fake.encoded, [[1], [2], [3], [2]])
        self.assertEqual(len(self.engine._image_feature_cache), 2)

    def test_evicted_entry_already_selected_for_batch_retains_its_exact_features(self):
        self.check([self.sample([RGB(1)])])
        self.engine._image_feature_cache_limit = self.engine._image_feature_cache_bytes
        self.check([self.sample([RGB(2)]), self.sample([RGB(1)])])
        self.assertEqual(self.fake.encoded, [[1], [2]])
        self.assertEqual(len(self.engine._image_feature_cache), 1)

    def test_entry_count_is_bounded_even_for_tiny_features(self):
        tensor = type(self.fake.torch.cat([]))
        tensor.numel = lambda value: len(value)
        for value in range(65):
            self.check([self.sample([RGB(value)])])
        self.assertEqual(len(self.engine._image_feature_cache), 64)
        self.assertNotIn(((RGB(0).size, RGB(0).tobytes()),), self.engine._image_feature_cache)

    def test_large_non_rgb_gpu_tiled_and_training_states_keep_uncached_path(self):
        for image, prep, training in ((RGB(2, (256, 256)), object(), False),
                (RGB(3), SimpleNamespace(on_gpu=True), False),
                (RGB(4), SimpleNamespace(split_edge=512), False), (RGB(5), object(), True)):
            self.engine.agent.prep = prep
            self.engine.agent.model.training = training
            for _ in range(2):
                self.check([self.sample([image])])
        image = RGB(6)
        image.mode = "L"
        self.engine.agent.model.training = False
        self.engine.agent.prep = object()
        for _ in range(2):
            self.check([self.sample([image])])
        self.assertEqual(len(self.fake.encoded), 10)
        self.assertEqual(self.engine._image_feature_cache, {})

    def test_model_processor_prep_device_and_dtype_changes_invalidate_features(self):
        sample = self.sample([RGB(1)])
        self.check([sample])
        for name, value in (("processor", SimpleNamespace(tokenizer=SimpleNamespace(pad_token_id=0))),
                            ("prep", object()), ("device", "cpu"), ("_torch_dtype", lambda: "fp32")):
            setattr(self.engine.agent, name, value)
            self.check([sample])
        self.engine.agent.model.training = True
        self.check([sample])
        self.assertEqual(self.engine._image_feature_cache, {})
        self.engine.agent.model.training = False
        self.check([sample])
        self.assertEqual(len(self.fake.encoded), 7)

    def test_oversize_features_or_disabled_cache_do_not_retain_entries(self):
        self.engine._image_feature_cache_limit = 1
        for _ in range(2):
            self.check([self.sample([RGB(1)])])
        self.assertEqual(self.engine._image_feature_cache, {})
        self.engine._image_feature_cache_limit = 0
        for _ in range(2):
            self.check([self.sample([RGB(1)])])
        self.assertEqual(len(self.fake.encoded), 4)
        self.assertEqual(self.engine._image_feature_cache_bytes, 0)

    def test_frozen_uncached_reference_matches_existing_fake_reference(self):
        samples = [self.sample([RGB(7), RGB(11)]), self.sample([RGB(13)], note="pot")]
        self.assertEqual(uncached_predict_many(self.engine, samples), self.fake.reference(samples))
        self.assertEqual(self.engine._image_feature_cache, {})

    def test_gpu_proof_refuses_live_port_before_any_model_load(self):
        probe = Mock()
        probe.__enter__ = Mock(return_value=probe)
        probe.__exit__ = Mock(return_value=False)
        probe.connect_ex.return_value = 0
        with patch.object(socket, "socket", return_value=probe), patch.object(srv, "Engine") as engine:
            with self.assertRaisesRegex(AssertionError, "Stop the managed service"):
                CapturedGPUProofTests().test_original_cold_and_cached_logits_and_wire_answers_are_exact()
        engine.assert_not_called()

    def test_failed_encode_or_question_validation_does_not_cache_a_reading(self):
        self.engine.agent.model.encode_images.side_effect = RuntimeError("encoder failure")
        with self.assertRaisesRegex(RuntimeError, "encoder failure"):
            self.engine.predict_many([self.sample([RGB(1)])])
        self.assertEqual(self.engine._image_feature_cache, {})
        self.assertEqual(self.engine._image_feature_cache_bytes, 0)
        with self.assertRaisesRegex(ValueError, "batch-question-invalid"):
            self.engine.predict_many([self.sample([RGB(1)], questions={"bad": {
                "type": "choice", "instructions": "invalid", "criteria": ["1", "2"]}})])
        self.assertEqual(self.engine._image_feature_cache, {})


@unittest.skipUnless(os.environ.get("LAYA_FEATURE_CACHE_PIXEL_PROOF") == "1", "optional captured RGB replay")
class CapturedPixelReplayTests(unittest.TestCase):
    def test_exact_prepared_pixel_recurrence_without_loading_model(self):
        from PIL import Image
        import laya_prep

        root = srv.ROOT
        captures = root / os.environ.get("LAYA_FEATURE_CACHE_CAPTURES", ".local/captures/utc-1791930788-730768600-practice")
        regions = json.loads((root / "crates/ingest/assets/laya/regions.json").read_text())["regions"]
        manifest = {row["frame_index"]: row for line in (captures / "manifest.jsonl").read_text().splitlines()
                    if (row := json.loads(line)).get("event") == "frame"}
        engine = srv.Engine.__new__(srv.Engine)
        engine.agent = SimpleNamespace(model=SimpleNamespace(training=False), processor=object(),
            prep=object(), device="fake-no-model", _torch_dtype=lambda: "fake-bf16")
        engine._image_feature_cache = {}
        engine._image_feature_cache_bytes = 0
        engine._image_feature_cache_limit = 16 * 1024 * 1024
        engine._image_feature_cache_context = None
        counts, frames = {}, 0
        for index in range(2, min(302, max(manifest)+1), 20):
            path = captures / ("frame-%010d.png" % index)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), manifest[index]["sha256"])
            with Image.open(path) as image:
                frame = image.convert("RGB")
            self.assertIsNone(engine._image_cache_key([frame]))
            frames += 1
            for region in ("pot", *("seat_%d_stack" % n for n in range(1, 7))):
                crop = frame.crop(laya_prep.box_px(regions[region], *frame.size))
                images, info = laya_prep.segment_glyphs(crop, "white" if region == "pot" else "gold")
                if not images or info["overflow"]:
                    continue
                key = engine._image_cache_key(images)
                self.assertEqual(key, engine._image_cache_key([image.copy() for image in images]))
                count = counts.setdefault(region, {"states": 0, "hits": 0})
                count["states"] += 1
                if key in engine._image_feature_cache:
                    count["hits"] += 1
                    entry = engine._image_feature_cache.pop(key)
                    engine._image_feature_cache[key] = entry
                else:
                    features = SimpleNamespace(numel=lambda: len(images)*64*576, element_size=lambda: 2,
                        detach=lambda: SimpleNamespace(clone=lambda: None))
                    engine._remember_image_features(key, {"ids": [64]*len(images)*64,
                        "n_images": len(images)}, features)
        self.assertGreater(frames, 2)
        self.assertTrue(counts)
        print(json.dumps({"proof": "exact_prepared_RGB_recurrence_CPU_only", "frames": frames,
            "source": str(captures.relative_to(root)), "per_region": counts,
            "cache_bytes_estimated_feature_storage": engine._image_feature_cache_bytes,
            "cache_entries": len(engine._image_feature_cache), "offline_only_not_live_hit_rate": True}, sort_keys=True))


@unittest.skipUnless(os.environ.get("LAYA_FEATURE_CACHE_GPU_PROOF") == "1", "controlled GPU restart only")
class CapturedGPUProofTests(unittest.TestCase):
    def test_original_cold_and_cached_logits_and_wire_answers_are_exact(self):
        # This suite loads ONE GPU model, and must never contend with the managed service.
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex((srv.HOST, srv.PORT)) == 0:
                self.fail("Stop the managed service in coordination with main before GPU proof")
        import torch
        from PIL import Image

        engine = srv.Engine(srv.load_pins())
        root = srv.ROOT
        captures = root / os.environ.get("LAYA_FEATURE_CACHE_CAPTURES", ".local/captures/utc-1791930788-730768600-practice")
        manifest = {row["frame_index"]: row for line in (captures / "manifest.jsonl").read_text().splitlines()
                    if (row := json.loads(line)).get("event") == "frame"}
        regions = json.loads((root / "crates/ingest/assets/laya/regions.json").read_text())["regions"]
        passes = {p["id"]: p for p in json.loads((root / "crates/ingest/assets/laya/question-set.json").read_text())["passes"]}
        groups, source_hashes = [], []

        def prepare(pid, frame):
            p = passes[pid]
            if pid == "p0_full":
                return [frame], *srv.readout_core_template(False)
            images = [frame.crop(engine.prep.box_px(regions[region], *frame.size)) for region in p["regions"]]
            questions = {}
            for q in p["questions"]:
                item = {key: q[key] for key in ("type", "instructions", "criteria") if key in q}
                if isinstance(item.get("criteria"), dict):
                    item["criteria"] = {label: q["criteria"][label] for label in q["option_order"]}
                questions[q["id"]] = item
            if p["layout"] == "glyphs":
                images, info = engine.prep.segment_glyphs(images[0], p["glyph_style"], srv.MAX_GLYPHS)
                self.assertFalse(info["overflow"])
                questions = {qid: q for qid, q in questions.items() if int(qid[1:]) <= len(images)}
            return images, p["note"], questions

        for index in (2, 17, 80):
            path = captures / ("frame-%010d.png" % index)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, manifest[index]["sha256"])
            source_hashes.append(digest)
            with Image.open(path) as image:
                frame = image.convert("RGB")
            for seat in (1, 3, 5):
                group = [prepare(pid, frame) for pid in ("p0_full", "p3_pot",
                         "p5_seat_%d_stack" % seat, "p5_seat_%d_stack" % (seat+1))]
                groups.append([sample for sample in group if sample[0] and sample[2]])
            board = prepare("p2_board", frame)
            groups.append([([frame], *srv.readout_core_template(True)), board])

        # Model warmup is separate from measured comparisons.
        uncached_predict_many(engine, groups[0])

        def run(method, capture_logits):
            logits, shapes, elapsed, encodes = [], [], [], []
            def encoded(module, args, output):
                encodes.append(tuple(output.shape))
            def scored(module, args, kwargs, output):
                shapes.append((tuple(args[0].shape), tuple(kwargs["image_hidden_states"].shape)))
                if capture_logits:
                    logits.append(output[0].detach().float().cpu().clone())
            original_encode = engine.agent.model.encode_images
            def encode(*args, **kwargs):
                output = original_encode(*args, **kwargs)
                encoded(None, args, output)
                return output
            engine.agent.model.encode_images = encode
            hook = engine.agent.model.register_forward_hook(scored, with_kwargs=True)
            try:
                answers = []
                for group in groups:
                    start = time.perf_counter()
                    answers.append(method(engine, group))
                    elapsed.append((time.perf_counter()-start)*1000)
            finally:
                hook.remove()
                engine.agent.model.encode_images = original_encode
            return answers, logits, shapes, elapsed, encodes

        original = run(uncached_predict_many, True)
        cold = run(srv.Engine.predict_many, True)
        warm = run(srv.Engine.predict_many, True)
        for result in (cold, warm):
            self.assertEqual(result[0], original[0])
            self.assertEqual(result[2], original[2])
            self.assertEqual(len(result[1]), len(original[1]))
            self.assertTrue(all(torch.equal(a, b) for a, b in zip(result[1], original[1])), "raw logits differ")
        self.assertLess(len(warm[4]), len(original[4]))
        # Timings exclude the validation hook's extra synchronous device-to-host copies.
        baseline_timing = run(uncached_predict_many, False)
        cached_timing = run(srv.Engine.predict_many, False)
        self.assertEqual(baseline_timing[0], cached_timing[0])
        print(json.dumps({"proof": "exact_original_logits_shapes_wire_answers", "frames": source_hashes,
            "source": str(captures.relative_to(root)), "states": sum(map(len, groups)),
            "groups": len(groups), "original_encodes": len(original[4]), "cold_encodes": len(cold[4]),
            "warm_encodes": len(warm[4]), "cache_bytes": engine._image_feature_cache_bytes,
            "cache_entries": len(engine._image_feature_cache), "offline_only_not_live": True,
            "uncached_group_p50_ms": round(statistics.median(baseline_timing[3]), 1),
            "cached_group_p50_ms": round(statistics.median(cached_timing[3]), 1),
            "uncached_total_ms": round(sum(baseline_timing[3]), 1),
            "cached_total_ms": round(sum(cached_timing[3]), 1)}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
