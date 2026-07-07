"""Export stitched beat-the-game runs (+ hard tracks) for the browser.

For each "replay" track: re-run the (deterministic) backtracking search to regenerate
the exact winning run, replay it capturing a per-tick pose stream, and write
<root>/replays/track<t>.json = {track vertices (px), spawn, poses, difficulty meta}.
For each "play-only" track: export just the vertices (instant, no search) so a human
can DRIVE the exact pinned hard track in ai_play.html and judge it.

Writes <root>/replays/manifest.json listing everything (the browser picker reads it).

Search params MATCH the beat study (snap_every 20, attempts 8, margin 400, budget 400k,
seed 770000+t) so the regenerated runs reproduce the study exactly.

Run: python autorun/export_replay.py [--replay 8,21,13] [--play 6,11,15,16,23]
       [--budget 400000] [--ckpt PATH]
"""
import os, sys, json, random
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)
from stable_baselines3 import PPO                                   # noqa: E402
import env as E                                                     # noqa: E402
from env import HillClimbEnv                                        # noqa: E402
from ground import make_ground                                     # noqa: E402
from constants import SPAWN_X, SCALE, GROUND_DISTANCE              # noqa: E402
from backtrack_search import (solve_track, replay_segments, BEAT_PX,  # noqa: E402
                              MAX_EP_STEPS)

DEFAULT_CKPT = os.path.join(ROOT, "checkpoints", "seed2_resume_11611776_steps.zip")
# Defaults: a few dramatic beaten tracks (cheap first) + hard tracks to drive.
DEFAULT_REPLAY = [8, 21, 13]          # 1925 (5k ticks), 1938 (22k), 1962 showpiece (164k)
DEFAULT_PLAY = [6, 11, 15, 16, 23]    # deep-backtrack hard tracks; 11 is the UNBEATEN holdout


def pin_ground(t):
    random.seed(987_000 + t)
    return make_ground(None, difficulty=0.0)


def track_payload(t, g):
    """Common track fields (vertices in px incl. closing verts, spawn)."""
    return {
        "track_id": t, "track_seed": 987_000 + t,
        "scale": SCALE, "frame_rate": 30, "spawn_x": SPAWN_X,
        "spawning_y": float(g.spawning_y), "distance": GROUND_DISTANCE,
        "vertices": [[round(float(x), 2), round(float(y), 2)] for x, y in g.vectors],
    }


def main():
    argv = sys.argv[1:]
    def popflag(name, default, cast=str):
        if name in argv:
            i = argv.index(name); v = argv[i + 1]; del argv[i:i + 2]; return cast(v)
        return default
    ckpt = popflag("--ckpt", DEFAULT_CKPT)
    budget = popflag("--budget", 400_000, int)
    replay_ids = [int(x) for x in popflag("--replay", ",".join(map(str, DEFAULT_REPLAY))).split(",") if x != ""]
    play_ids = [int(x) for x in popflag("--play", ",".join(map(str, DEFAULT_PLAY))).split(",") if x != ""]

    outdir = os.path.join(REPO, "replays"); os.makedirs(outdir, exist_ok=True)
    print(f"[export_replay] ckpt={os.path.basename(ckpt)} replay={replay_ids} "
          f"play-only={play_ids} -> {outdir}", flush=True)
    model = PPO.load(ckpt, device="auto")
    manifest = []
    orig = E._make_ground

    # --- replay tracks: solve + record pose stream ---
    try:
        for t in replay_ids:
            g = pin_ground(t)
            E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
            env = HillClimbEnv(max_episode_steps=MAX_EP_STEPS,
                               randomize_terrain=False, per_wheel_obs=True)
            r = solve_track(env, model, t, 20, 8, 400.0, budget, 2, 8, 2, BEAT_PX)
            if not r["solved"] or r.get("segments") is None:
                print(f"  track {t}: NOT solved within budget ({r['reason']}, "
                      f"score {(r['max_x']-SPAWN_X)/10:.0f}) -> exporting vertices only",
                      flush=True)
                play_ids.append(t); env.close(); continue
            poses, final_x, dims = replay_segments(env, r["segments"])
            score = (final_x - SPAWN_X) / 10.0
            n_act = sum(len(s["actions"]) for s in r["segments"])
            assert len(poses) == n_act, f"pose/action mismatch {len(poses)} vs {n_act}"
            payload = track_payload(t, g)
            payload.update(name=f"track {t} (BEAT {score:.0f})", beat_score=round(score, 1),
                           difficulty={"reason": r["reason"], "depth": r["depth"],
                                       "bottlenecks": r["bottlenecks"],
                                       "attempts": r["n_attempts"], "ticks": r["ticks"]},
                           dims=dims, n_frames=len(poses), poses=poses)
            fn = f"track{t}.json"
            with open(os.path.join(outdir, fn), "w") as f:
                json.dump(payload, f, separators=(",", ":"))
            sz = os.path.getsize(os.path.join(outdir, fn)) / 1e6
            print(f"  track {t}: BEAT replay {len(poses)} frames, score {score:.1f} "
                  f"-> {fn} ({sz:.1f} MB)", flush=True)
            manifest.append({"file": fn, "name": payload["name"], "track_id": t,
                             "kind": "replay", "beat_score": payload["beat_score"],
                             "depth": r["depth"], "ticks": r["ticks"], "playable": True})
            env.close()
    finally:
        E._make_ground = orig

    # --- play-only tracks: vertices only (instant) ---
    for t in sorted(set(play_ids)):
        if any(m["track_id"] == t for m in manifest):
            continue
        g = pin_ground(t)
        payload = track_payload(t, g)
        payload["name"] = f"track {t} (hard - drive it)"
        fn = f"track{t}.json"
        with open(os.path.join(outdir, fn), "w") as f:
            json.dump(payload, f, separators=(",", ":"))
        print(f"  track {t}: vertices only -> {fn}", flush=True)
        manifest.append({"file": fn, "name": payload["name"], "track_id": t,
                         "kind": "play", "playable": True})

    manifest.sort(key=lambda m: m["track_id"])
    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump({"tracks": manifest}, f, indent=2)
    print(f"\n  manifest -> {os.path.join(outdir, 'manifest.json')}  ({len(manifest)} tracks)",
          flush=True)


if __name__ == "__main__":
    main()
