"""Go-Explore-style backtracking search ("save-scum") on the frozen policy.

The chaos finding (jitter_probe) says completion is gated by per-SECTION survival
*probability* in the steep back third, and Best-of-X (full restart each attempt)
plateaus at ~82.5% because a whole run must survive every section at once -- a
product of small numbers. This harness instead FACTORIZES that product: when the
policy dies at a bottleneck, it restores a saved physics state a little way back,
perturbs the movement (a short random action burst), and lets the policy continue.
Retry a few times; if the same wall keeps killing it, rewind FURTHER (iterative
deepening over the entry state into the wall). Commit each cleared section and move
on. The committed trajectory is one continuous simulation (we keep a single V8 world
and only restore snapshots born in it), so the cleared run stitches together exactly
-- the only "cheat" seams are the sub-section random bursts.

This is a CONSTRUCTED replay, not a better policy: it answers "can we build full
completions, how reliably, and how cheaply" vs Best-of-X -- and it localizes the
tracks that resist even deep backtracking (the true on/off-motor hard core).

Restore uses the death-safe path (reset_car() then restore_state(); see
test_saverestore.py "reset"). Policy resume is exact: we snapshot the env-internal
coyote/stuck/progress counters and the 4-frame stack alongside the physics blob.

Tracks are pinned exactly like best_of_k.py (seed the global RNG right before
make_ground, inject the Ground via env._make_ground) so completion% is directly
comparable; --baseline-k also runs paired Best-of-K on the same tracks.

Run: python autorun/backtrack_search.py [n_tracks=30] [--ckpt PATH] [--baseline-k 0]
       [--smoke] [--snap-every 20] [--attempts 8] [--margin 400] [--budget 400000]
"""
import os, sys, json, random
import numpy as np

os.environ["HCR_PER_WHEEL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from stable_baselines3 import PPO                                   # noqa: E402
import env as E                                                     # noqa: E402
from env import HillClimbEnv                                        # noqa: E402
from ground import make_ground                                     # noqa: E402
from constants import (GROUND_DISTANCE, SPAWN_X, SCALE,             # noqa: E402
                       CHASSIS_WIDTH, CHASSIS_HEIGHT)

DEFAULT_CKPT = os.path.join(ROOT, "checkpoints", "seed2_resume_11611776_steps.zip")
END_PX = GROUND_DISTANCE - 350.0
COMPLETE_PX = END_PX - 600.0          # soft "completion" line used in the rest of the repo (score 1790)
# "Beating the game" = max_x reaches the END of the solid terrain (last vertex
# ~19185px = score 1883) and launches off the lip into the void. We target the lip;
# reaching it requires the fly-off, and the arc beyond pushes the real score to
# ~1910-1925 (measured; see diagnostics/measure_track_end.py). Default search goal.
BEAT_PX = 19180.0                     # score 1883 (max_x of the last solid vertex)

OBS_DIM = 12          # per-wheel, lookahead 6, rear 0
N_STACK = 4
MAX_EP_STEPS = 8000   # high so truncation never causes a "death" during search
BRANCH_MAX_TICKS = 5000

# ---- frame-stack (replicate VecFrameStack(4): zero-pad on reset, roll left) ----
def init_stack(obs0):
    fb = np.zeros(OBS_DIM * N_STACK, dtype=np.float32)
    fb[-OBS_DIM:] = obs0
    return fb

def push_stack(fb, obs):
    fb[:-OBS_DIM] = fb[OBS_DIM:]
    fb[-OBS_DIM:] = obs

# ---- snapshot / restore of the FULL resumable state ----------------------------
def make_snap(env, fb, aidx):
    phys = env._js.save_state()
    chassis_x_m = json.loads(phys)["bodies"][0][0]
    return {
        "phys": phys, "fb": fb.copy(),
        "lg_r": env.last_grounded_rear, "lg_f": env.last_grounded_front,
        "maxd": env._max_dist_px, "stuck": env._stuck_change_count,
        "steps": env.steps, "prevx": env.prev_chassis_x_m,
        "x_px": chassis_x_m * SCALE, "aidx": aidx,
    }

def restore(env, snap):
    env._js.reset_car()                 # death-safe: rebuilds joints
    env._js.restore_state(snap["phys"])  # then teleport bodies (baked anchors re-satisfy)
    env.last_grounded_rear = snap["lg_r"]; env.last_grounded_front = snap["lg_f"]
    env._max_dist_px = snap["maxd"]; env._stuck_change_count = snap["stuck"]
    env.steps = snap["steps"]; env.prev_chassis_x_m = snap["prevx"]
    return snap["fb"].copy()

def commit_segments(segments, seam, b_actions):
    """Splice a winning branch into the explicit segment list so the committed run
    can later be replayed EXACTLY by restoring only at the true commit seams (the
    only points where the search did reset_car+restore). Truncates the segment that
    contains the seam's flat action-index, drops everything after it, and appends the
    new segment {start: seam snapshot, actions: branch actions}."""
    S = seam["aidx"]; base = 0; out = []
    for seg in segments:
        L = len(seg["actions"])
        if S >= base + L:
            out.append(seg); base += L
        else:
            if S - base > 0:
                out.append({"start": seg["start"], "actions": seg["actions"][:S - base]})
            break
    out.append({"start": seam, "actions": list(b_actions)})
    return out

# ---- one forward rollout from the env's CURRENT state --------------------------
def roll(env, model, fb, start_aidx, burst, snap_every, max_ticks, tick_left,
         target_px):
    """Play forward (burst actions first, then the deterministic policy), recording
    the action list and periodic snapshots. Once max_x crosses target_px the run is
    'beaten', but we keep stepping until natural death so the full fly-off ARC (and
    its true ~1920 score) is captured. Returns (actions, snaps, max_x_px, status,
    ticks) with status in {complete, dead, trunc, budget}."""
    actions, snaps = [], []
    max_x = env._max_dist_px
    beaten = False
    t = 0
    while True:
        if t % snap_every == 0:
            snaps.append(make_snap(env, fb, start_aidx + len(actions)))
        if t < len(burst):
            act = burst[t]
        else:
            a, _ = model.predict(fb.reshape(1, -1), deterministic=True)
            act = int(a[0])
        obs, _r, term, trunc, info = env.step(act)
        push_stack(fb, obs)
        actions.append(act); t += 1
        max_x = info["max_distance_px"]
        if max_x >= target_px:
            beaten = True                          # reached the lip; let the arc play out
        if term:
            return actions, snaps, max_x, ("complete" if beaten else "dead"), t
        if trunc or t >= max_ticks:
            return actions, snaps, max_x, ("complete" if beaten else "trunc"), t
        if t >= tick_left:
            return actions, snaps, max_x, ("complete" if beaten else "budget"), t

# ---- backtracking solve for one pinned track -----------------------------------
def solve_track(env, model, t, snap_every, attempts, margin, budget,
                burst_min, burst_max, init_depth, target_px, verbose=False):
    obs0, _ = env.reset()                        # builds the pinned world at SPAWN_X
    fb = init_stack(obs0)                         # use reset's obs (don't re-_build_obs)
    rng = random.Random(770_000 + t)

    ticks_used = 0
    actions, snaps, max_x, status, n = roll(
        env, model, fb, 0, [], snap_every, MAX_EP_STEPS, budget, target_px)
    ticks_used += n
    segments = [{"start": snaps[0], "actions": actions}]   # seg0: spawn snapshot + canonical
    if status == "complete":
        return dict(solved=True, reason="single-shot", ticks=ticks_used, max_x=max_x,
                    depth=0, bottlenecks=0, n_attempts=0, final_death=None,
                    segments=segments)

    committed = actions; csnaps = snaps           # one action-index coordinate system
    bottleneck = max_x
    depth = init_depth
    n_attempts = 0; bottlenecks = 0; max_depth = 0

    while ticks_used < budget:
        if depth > len(csnaps):                   # rewound past spawn -> give up
            return dict(solved=False, reason="exhausted", ticks=ticks_used,
                        max_x=bottleneck, depth=depth, bottlenecks=bottlenecks,
                        n_attempts=n_attempts, final_death=bottleneck, segments=None)
        seam = csnaps[-depth]
        max_depth = max(max_depth, depth)
        cleared = False
        for _ in range(attempts):
            if ticks_used >= budget:
                break
            fb = restore(env, seam)
            blen = rng.randint(burst_min, burst_max)
            burst = [rng.randint(0, 2) for _ in range(blen)]
            b_actions, b_snaps, b_max, b_status, n = roll(
                env, model, fb, seam["aidx"], burst, snap_every,
                BRANCH_MAX_TICKS, budget - ticks_used, target_px)
            ticks_used += n; n_attempts += 1
            if b_status == "complete":
                segments = commit_segments(segments, seam, b_actions)
                return dict(solved=True, reason="backtrack", ticks=ticks_used,
                            max_x=b_max, depth=max_depth, bottlenecks=bottlenecks + 1,
                            n_attempts=n_attempts, final_death=None, segments=segments)
            if b_max >= bottleneck + margin:       # cleared this wall, died later
                committed = committed[:seam["aidx"]] + b_actions
                csnaps = [s for s in csnaps if s["aidx"] < seam["aidx"]] + b_snaps
                segments = commit_segments(segments, seam, b_actions)
                bottleneck = b_max; bottlenecks += 1
                depth = init_depth; cleared = True
                if verbose:
                    print(f"      cleared -> new bottleneck {bottleneck:.0f}px "
                          f"(ticks {ticks_used})", flush=True)
                break
        if not cleared:
            depth += 1                             # iterative deepening: rewind further
    return dict(solved=False, reason="budget", ticks=ticks_used, max_x=bottleneck,
                depth=max_depth, bottlenecks=bottlenecks, n_attempts=n_attempts,
                final_death=bottleneck, segments=None)

# ---- exact replay of a solved run -> per-tick pose stream ----------------------
def replay_segments(env, segments):
    """Re-derive the committed run EXACTLY by restoring each segment's start
    snapshot and replaying its recorded actions, capturing a per-tick pose. Restores
    happen ONLY at the true commit seams (where the search did reset_car+restore), so
    the run is continuous within each segment. `env._js.step(a)` is the same physics
    step the search used (env.step calls step_and_state -> step), so this reproduces
    the winning trajectory bit-for-bit. Returns (poses, final_chassis_x_px).

    Pose units are METERS (matching Box2D bodies) so the browser's sprite-draw
    helpers work via mocked bodies; widths/radii are constants the browser knows."""
    poses = []
    last_x = 0.0
    dims = None
    for seg in segments:
        restore(env, seg["start"])
        for a in seg["actions"]:
            env._js.step(a)
            rs = env._js.render_state()
            st = env._js.state(env.lookahead_n, 5, 0, 5)
            last_x = st["x"] * SCALE
            if dims is None:                         # body sizes (px) for the browser ghost
                dims = {"chassis_w": CHASSIS_WIDTH, "chassis_h": CHASSIS_HEIGHT,
                        "wheel_r": rs["wheels"][0]["radius_px"],
                        "torso_w": rs["torso"]["width_px"], "torso_h": rs["torso"]["height_px"],
                        "head_r": rs["head"]["radius_px"]}
            poses.append({
                "chassis": {"x": st["x"], "y": st["y"], "angle": st["angle"]},
                "wheels": [{"x": w["x_px"] / SCALE, "y": w["y_px"] / SCALE,
                            "angle": w["angle"]} for w in rs["wheels"]],
                "torso": {"x": rs["torso"]["x_px"] / SCALE,
                          "y": rs["torso"]["y_px"] / SCALE, "angle": rs["torso"]["angle"]},
                "head": {"x": rs["head"]["x_px"] / SCALE, "y": rs["head"]["y_px"] / SCALE,
                         "angle": rs["head"]["angle"]},
                "dead": bool(rs["dead"]),
            })
    return poses, last_x, dims

# ---- paired Best-of-K baseline on the SAME pinned track ------------------------
def baseline_bestofk(env, model, t, K, target_px):
    """attempt 0 canonical + K-1 with +-1px spawn jitter (== best_of_k.py). Returns
    (beaten_bool, best_score, total_ticks). Beaten == reached target_px (the lip)."""
    env.reset()
    raw = env
    sy = raw._ground.spawning_y
    jr = random.Random(55_000 + t)
    beaten = False; ticks = 0; best = 0.0
    for k in range(K):
        if k == 0:
            raw._js.set_spawn(float(SPAWN_X), float(sy))
        else:
            dx = (jr.random() - 0.5) * 2.0; dy = (jr.random() - 0.5) * 2.0
            raw._js.set_spawn(SPAWN_X + dx, sy + dy)
        obs, _ = env.reset()
        fb = init_stack(obs)
        done = False; info = {}
        while not done:
            a, _ = model.predict(fb.reshape(1, -1), deterministic=True)
            obs, _r, term, trunc, info = env.step(int(a[0]))
            push_stack(fb, obs); ticks += 1
            done = term or trunc
        best = max(best, info.get("max_distance_px", 0.0))
        if info.get("max_distance_px", 0.0) >= target_px:
            beaten = True
            break                                  # early-stop on beat (like ai_play.html)
    return beaten, (best - SPAWN_X) / 10.0, ticks

def main():
    argv = sys.argv[1:]
    def popflag(name, default=None, cast=str):
        if name in argv:
            i = argv.index(name); v = argv[i + 1]; del argv[i:i + 2]; return cast(v)
        return default
    ckpt = popflag("--ckpt", DEFAULT_CKPT)
    baseline_k = popflag("--baseline-k", 0, int)
    snap_every = popflag("--snap-every", 20, int)
    attempts = popflag("--attempts", 8, int)
    margin = popflag("--margin", 400.0, float)
    budget = popflag("--budget", 400_000, int)
    target_px = popflag("--target-px", BEAT_PX, float)  # default: beat the game (the lip)
    tracks_sel = popflag("--tracks", None)               # e.g. "11" or "7,12,14" -> only those track ids
    smoke = "--smoke" in argv
    if smoke:
        argv.remove("--smoke")
    pos = [a for a in argv if not a.startswith("--")]
    n_tracks = int(pos[0]) if pos else (3 if smoke else 30)
    track_ids = ([int(x) for x in tracks_sel.split(",")] if tracks_sel
                 else list(range(n_tracks)))
    burst_min, burst_max, init_depth = 2, 8, 2

    goal = "BEAT-THE-GAME (fly off the lip)" if target_px >= BEAT_PX else "soft-complete"
    print(f"[backtrack_search] ckpt={os.path.basename(ckpt)}  tracks={track_ids}  "
          f"goal={goal} target={target_px:.0f}px (score {(target_px-SPAWN_X)/10:.0f})  "
          f"snap_every={snap_every} attempts={attempts} margin={margin:.0f} "
          f"budget={budget} baseline_k={baseline_k}", flush=True)
    model = PPO.load(ckpt, device="auto")

    tracks = []
    for t in track_ids:
        random.seed(987_000 + t)
        tracks.append((t, make_ground(None, difficulty=0.0)))

    n_total = len(tracks)
    results = []
    base = []
    orig = E._make_ground
    try:
        for i, (t, g) in enumerate(tracks):
            E._make_ground = lambda seed, difficulty=0.0, _g=g: _g
            env = HillClimbEnv(max_episode_steps=MAX_EP_STEPS,
                               randomize_terrain=False, per_wheel_obs=True)
            r = solve_track(env, model, t, snap_every, attempts, margin, budget,
                            burst_min, burst_max, init_depth, target_px, verbose=smoke)
            results.append(r)
            sc = max(0.0, (r["max_x"] - SPAWN_X) / 10.0)
            tag = "BEAT" if r["solved"] else "FAILED"
            print(f"  [{i+1}/{n_total}] track{t:>2d} {tag:>6s} [{r['reason']:>10s}]  "
                  f"ticks={r['ticks']:>7d}  depth={r['depth']:>2d}  "
                  f"bottlenecks={r['bottlenecks']:>2d}  attempts={r['n_attempts']:>3d}  "
                  f"score={sc:7.1f}", flush=True)
            if baseline_k > 0:
                bc, bsc, bt = baseline_bestofk(env, model, t, baseline_k, target_px)
                base.append((bc, bsc, bt))
                print(f"           best-of-{baseline_k}: "
                      f"{'BEAT' if bc else 'failed':>6s}  score={bsc:7.1f}  ticks={bt}",
                      flush=True)
            env.close()
    finally:
        E._make_ground = orig

    solved = np.array([r["solved"] for r in results])
    ticks = np.array([r["ticks"] for r in results])
    reasons = [r["reason"] for r in results]
    rc = {k: reasons.count(k) for k in ("single-shot", "backtrack", "budget", "exhausted")}
    print(f"\n[backtrack_search] {n_total} pinned tracks")
    print(f"  BEAT rate:         {100*solved.mean():5.1f}%  ({solved.sum()}/{n_total})")
    print(f"    single-shot={rc['single-shot']}  via-backtrack={rc['backtrack']}  "
          f"| failed: budget-capped={rc['budget']}  rewound-to-spawn={rc['exhausted']}")
    print(f"  mean ticks/track:  {ticks.mean():9.0f}   (solved-only "
          f"{ticks[solved].mean() if solved.any() else 0:.0f})")
    print(f"  max rewind depth:  {max(r['depth'] for r in results)}  "
          f"(snap_every={snap_every} ticks)")
    if baseline_k > 0 and base:
        bc = np.array([b[0] for b in base]); bt = np.array([b[2] for b in base])
        print(f"  best-of-{baseline_k} BEAT rate: {100*bc.mean():5.1f}%  "
              f"mean ticks/track {bt.mean():.0f}")
        print(f"  paired: backtrack-only beats={int((solved & ~bc).sum())}  "
              f"bestofk-only={int((~solved & bc).sum())}  "
              f"both={int((solved & bc).sum())}  neither={int((~solved & ~bc).sum())}")

    stem = os.path.splitext(os.path.basename(ckpt))[0]
    suffix = "" if tracks_sel is None else "_sel" + "-".join(map(str, track_ids))[:40]
    outdir = os.path.join(HERE, "backtrack_runs"); os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"backtrack_{stem}{suffix}.npz")
    np.savez(out,
             solved=solved, ticks=ticks, track_ids=np.array(track_ids),
             max_x=np.array([r["max_x"] for r in results]),
             depth=np.array([r["depth"] for r in results]),
             bottlenecks=np.array([r["bottlenecks"] for r in results]),
             n_attempts=np.array([r["n_attempts"] for r in results]),
             reason=np.array([r["reason"] for r in results]),
             complete_px=COMPLETE_PX, n_tracks=n_total)
    print(f"\n  outcomes -> {out}")


if __name__ == "__main__":
    main()
