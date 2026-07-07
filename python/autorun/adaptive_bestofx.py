"""A1: Adaptive Best-of-X allocation, evaluated OFFLINE on a recorded attempt matrix.

The browser "Best of X" spends a FIXED X attempts on every track. But a human
clears ~90-95% in ~5 tries by NOT wasting tries: they stop once a level is
solved and keep retrying the ones that look winnable. This script quantifies how
much that adaptivity is worth, using the per-track x K attempt matrix recorded by
best_of_k.py (no new rollouts needed).

The matrix `dist[t, a]` = max_distance_px of attempt `a` on track `t` (attempt 0
= canonical spawn, 1.. = +-1px jittered), in the exact order a browser would run
them. A track is "completed" on an attempt iff that attempt's distance >=
complete_px.

We compare, at MATCHED average budget (attempts/track), several allocation rules:
  - uniform-K          : every track gets exactly K attempts (the current browser).
  - stop-on-completion : attempts in order until solved or cap; dominates uniform
                         (saves the budget that uniform wastes after a solve).
  - adaptive (deployable): base m0 attempts each, stop solved tracks, then spend
                         the saved budget on the most-promising UNSOLVED tracks,
                         ranked by a signal available in the browser (how far the
                         best attempt got, or how spread-out the deaths are).
  - oracle upper bound : greedy by each track's TRUE completion probability
                         (cheats; the ceiling any adaptive rule could reach).

Run: python autorun/adaptive_bestofx.py [best_of_k_<stem>.npz]
     (defaults to the newest best_of_k_*.npz in this folder)
"""
import os, sys, glob
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    z = np.load(path, allow_pickle=True)
    dist = z["dist"].astype(float)            # (n_tracks, k_max)
    complete_px = float(z["complete_px"])
    spawn_x = float(z["spawn_x"])
    ckpt = str(z["ckpt"]) if "ckpt" in z else os.path.basename(path)
    return dist, complete_px, spawn_x, ckpt


def score(dist, spawn_x):
    return np.maximum(0.0, (dist - spawn_x) / 10.0)


def uniform_curve(dist, complete_px, spawn_x, k_max):
    """Completion% / mean best-score / budget for uniform Best-of-K, K=1..k_max."""
    comp = dist >= complete_px
    rows = []
    for k in range(1, k_max + 1):
        pref = dist[:, :k]
        completion = 100.0 * comp[:, :k].any(axis=1).mean()
        best = pref.max(axis=1)
        rows.append((k, float(k), completion, float(score(best, spawn_x).mean())))
    return rows  # (label_k, avg_budget, completion%, mean_score)


def stop_on_completion(dist, complete_px, k_cap):
    """Attempts in order until solved or k_cap. Returns (completion%, avg_budget)."""
    comp = dist[:, :k_cap] >= complete_px
    n = dist.shape[0]
    budget = np.full(n, k_cap, dtype=float)
    solved = np.zeros(n, dtype=bool)
    for t in range(n):
        hit = np.argmax(comp[t]) if comp[t].any() else -1
        if hit >= 0:
            solved[t] = True
            budget[t] = hit + 1  # stop right after the solving attempt
    return 100.0 * solved.mean(), float(budget.mean())


def adaptive(dist, complete_px, spawn_x, m0, k_cap, target_avg, signal="best_dist"):
    """Deployable adaptive rule, evaluated on the recorded order of attempts.

    Phase 1: give every track up to m0 attempts (stop early if solved).
    Phase 2: with the budget saved from solved/cheap tracks, repeatedly grant ONE
             more attempt to the highest-ranked UNSOLVED track until the average
             budget hits target_avg or every track is solved/capped. Ranking uses
             only information a browser already has after the attempts run so far:
               best_dist : how far the best attempt on that track has reached
                           (closest-to-finish first -- "this one looks winnable").
               spread    : stop-position spread across its attempts so far
                           (chaotic tracks respond to more tries; see jitter_probe).
    Returns (completion%, avg_budget).
    """
    n, k_max = dist.shape
    k_cap = min(k_cap, k_max)
    comp = dist >= complete_px
    used = np.zeros(n, dtype=int)
    solved = np.zeros(n, dtype=bool)

    def run_one_more(t):
        """Reveal track t's next attempt; update solved/used."""
        a = used[t]
        used[t] += 1
        if comp[t, a]:
            solved[t] = True

    # Phase 1: base allocation.
    for t in range(n):
        for _ in range(m0):
            if solved[t] or used[t] >= k_cap:
                break
            run_one_more(t)

    # Phase 2: spend the rest of the average-budget pool on the best candidates.
    total_budget = int(round(target_avg * n))
    while used.sum() < total_budget:
        cand = [t for t in range(n) if not solved[t] and used[t] < k_cap]
        if not cand:
            break
        if signal == "best_dist":
            rank = max(cand, key=lambda t: dist[t, :used[t]].max())
        elif signal == "spread":
            rank = max(cand, key=lambda t: (dist[t, :used[t]].max() - dist[t, :used[t]].min()))
        else:
            raise ValueError(signal)
        run_one_more(rank)

    return 100.0 * solved.mean(), float(used.mean())


def oracle_upper(dist, complete_px, k_cap, target_avg):
    """Greedy upper bound: spend each attempt on the unsolved track with the
    highest TRUE per-attempt completion probability. Cheats (uses full matrix);
    bounds what any adaptive rule could achieve at this budget."""
    n, k_max = dist.shape
    k_cap = min(k_cap, k_max)
    comp = dist >= complete_px
    p = comp[:, :k_cap].mean(axis=1)        # empirical completion prob / attempt
    used = np.zeros(n, dtype=int)
    solved = np.zeros(n, dtype=bool)
    total_budget = int(round(target_avg * n))
    # Only tracks with p>0 are ever winnable; give attempts to the highest-p
    # unsolved track each step.
    while used.sum() < total_budget:
        cand = [t for t in range(n) if not solved[t] and used[t] < k_cap and p[t] > 0]
        if not cand:
            break
        t = max(cand, key=lambda t: p[t])
        a = used[t]; used[t] += 1
        if comp[t, a]:
            solved[t] = True
    return 100.0 * solved.mean(), float(used.mean())


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        cands = sorted(glob.glob(os.path.join(HERE, "best_of_k_*.npz")), key=os.path.getmtime)
        if not cands:
            sys.exit("no best_of_k_*.npz found -- run best_of_k.py first")
        path = cands[-1]

    dist, complete_px, spawn_x, ckpt = load(path)
    n, k_max = dist.shape
    print(f"[adaptive_bestofx] {os.path.basename(path)}  ckpt={ckpt}")
    print(f"  {n} tracks, {k_max} attempts each, complete_px={complete_px:.0f}\n")

    uni = uniform_curve(dist, complete_px, spawn_x, k_max)
    print("  uniform Best-of-K (current browser):")
    print(f"  {'K':>3s}  {'budget':>6s}  {'completion%':>11s}  {'mean score':>10s}")
    for k, b, c, s in uni:
        print(f"  {k:>3d}  {b:>6.1f}  {c:>10.1f}%  {s:>10.1f}")

    # Compare allocation rules at a few matched average budgets.
    print("\n  matched-budget comparison (completion%):")
    print(f"  {'avg budget':>10s}  {'uniform':>8s}  {'stop-on-cmp':>11s}  "
          f"{'adapt(dist)':>11s}  {'adapt(sprd)':>11s}  {'oracle':>7s}")
    uni_comp = {b: c for (k, b, c, s) in uni}
    for target in [3.0, 5.0, 8.0, 10.0, 15.0, 20.0]:
        if target > k_max:
            continue
        # uniform at the nearest integer K = target
        ku = int(round(target))
        u = uni_comp.get(float(ku), float("nan"))
        soc_c, soc_b = stop_on_completion(dist, complete_px, ku)
        ad_c, ad_b = adaptive(dist, complete_px, spawn_x, m0=3, k_cap=k_max,
                              target_avg=target, signal="best_dist")
        as_c, as_b = adaptive(dist, complete_px, spawn_x, m0=3, k_cap=k_max,
                              target_avg=target, signal="spread")
        or_c, or_b = oracle_upper(dist, complete_px, k_cap=k_max, target_avg=target)
        print(f"  {target:>10.1f}  {u:>7.1f}%  {soc_c:>10.1f}%  "
              f"{ad_c:>10.1f}%  {as_c:>10.1f}%  {or_c:>6.1f}%")

    print("\n  notes: stop-on-cmp completion == uniform at same K but uses less"
          " budget (shown via avg budget); adapt/oracle spend that saved budget"
          " on unsolved tracks. Bigger adapt-vs-uniform gap == more headroom for"
          " a browser adaptive-X.")


if __name__ == "__main__":
    main()
