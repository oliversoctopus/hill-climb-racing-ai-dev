"""Self-imitation fine-tune (phase 2): advantage-weighted BC on harvested
lucky-rollout segments, with a KL anchor to the frozen champion.

Loss (policy net only — the critic is untouched):

    L = -E_demo[ w(s,a) * log pi(a|s) ]  +  kl_coef * E_demo[ KL(pi_frozen || pi) ]

Weighting modes:
    --weight seg (DEFAULT): segment-level, w = (d_att - d_det) / seg-norm —
        how much this lucky attempt beat the deterministic baseline ON THE
        SAME TRACK. This is the correct counterfactual comparison; the
        critic-based per-step advantage is NOT: V(s) is the critic's
        distribution-average expectation, and inside steep sections even a
        winning attempt's realized return sits below that optimistic average
        (slow progress + later deaths inside the gamma-horizon), so
        max(0, rtg - V) zeroes out ~99% of the data (measured on the pilot:
        0.7% positive). Kept as ablations:
    --weight adv:     max(0, rtg - V_frozen(s))   (per-step critic advantage)
    --weight exp:     clip(exp((rtg - V_frozen(s))/beta), 0, wmax)  (AWR-style)
    --weight uniform: 1

Weights are normalized to mean 1 over positive entries, so kl_coef and lr
keep their meaning across datasets/modes. The KL anchor is evaluated on the
demo states (where drift happens); general driving is additionally protected
by training only on divergence segments.

Reports per epoch: BC loss, KL, and the ACTION-MATCH rate split by FORK vs
non-fork steps (is_fork = demo action differed from the champion's argmax at
harvest time). Fork-match starting near 0% and rising is the direct measure
of behavioral shift; non-fork match staying ~100% shows the anchor is
holding. Saves a normal SB3 .zip after every epoch (<out>_ep<N>.zip) + final
<out>.zip, so eval.py / rc_scan.py / export_onnx.py work unchanged
(snapshot-scan the epochs: final != best applies to BC epochs just as it
does to PPO steps).

Run:
  python\\.venv\\Scripts\\python.exe python\\finetune_sil.py ^
      python\\checkpoints\\base_a_8000000_steps.zip python\\demos\\base_a_h1.npz ^
      --out python\\checkpoints\\sil_a --epochs 10 --kl-coef 1.0
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

os.environ.setdefault("HCR_PER_WHEEL", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import torch as th  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402


def compute_weights(model_frozen, d: dict, obs: th.Tensor, rtg: th.Tensor,
                    mode: str, beta: float, wmax: float,
                    device, batch: int = 8192) -> th.Tensor:
    """Demo weights, normalized to mean 1 over positive entries."""
    if mode == "uniform":
        return th.ones_like(rtg)
    if mode == "seg":
        # Segment-level counterfactual: how far this attempt got past the
        # deterministic baseline on the SAME track, broadcast to its steps.
        gain_px = np.asarray(d["seg_d_att"] - d["seg_d_det"], dtype=np.float32)
        lens = np.asarray(d["seg_end"] - d["seg_start"], dtype=np.int64)
        w_np = np.repeat(np.maximum(gain_px, 0.0), lens)
        w = th.as_tensor(w_np, dtype=th.float32, device=device)
    else:
        vals = []
        with th.no_grad():
            for i in range(0, len(obs), batch):
                vals.append(model_frozen.policy.predict_values(obs[i:i + batch]).squeeze(-1))
        adv = rtg - th.cat(vals)
        if mode == "adv":
            w = th.clamp(adv, min=0.0)
        elif mode == "exp":
            w = th.clamp(th.exp(adv / beta), max=wmax)
        else:
            raise ValueError(mode)
    pos = w > 0
    if pos.any():
        w = w / w[pos].mean()
    return w


@th.no_grad()
def action_match(model, obs: th.Tensor, actions: th.Tensor,
                 mask: th.Tensor, batch: int = 8192) -> float:
    """Fraction of (masked) demo steps where argmax(pi) == demo action."""
    if mask.sum() == 0:
        return float("nan")
    hits, total = 0, 0
    idx = th.nonzero(mask, as_tuple=False).squeeze(-1)
    for i in range(0, len(idx), batch):
        j = idx[i:i + batch]
        dist = model.policy.get_distribution(obs[j])
        am = dist.distribution.logits.argmax(dim=-1)
        hits += int((am == actions[j]).sum())
        total += len(j)
    return hits / total


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("checkpoint", help="champion PPO .zip to fine-tune")
    p.add_argument("demos", help="harvest .npz from harvest.py")
    p.add_argument("--out", required=True, help="output path prefix (no .zip)")
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=1024)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--kl-coef", type=float, default=1.0)
    p.add_argument("--weight", choices=("seg", "adv", "exp", "uniform"), default="seg")
    p.add_argument("--beta", type=float, default=5.0, help="AWR temperature (--weight exp)")
    p.add_argument("--wmax", type=float, default=20.0, help="weight clip (--weight exp)")
    p.add_argument("--max-grad-norm", type=float, default=0.5)
    p.add_argument("--device", default="auto")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    th.manual_seed(args.seed)

    model = PPO.load(args.checkpoint, device=args.device)
    frozen = PPO.load(args.checkpoint, device=args.device)
    frozen.policy.set_training_mode(False)
    for prm in frozen.policy.parameters():
        prm.requires_grad_(False)
    device = model.policy.device

    d = np.load(args.demos)
    obs = th.as_tensor(d["obs"], dtype=th.float32, device=device)
    actions = th.as_tensor(d["actions"], dtype=th.long, device=device)
    rtg = th.as_tensor(d["rtg"], dtype=th.float32, device=device)
    n = len(actions)
    print(f"[sil] {n} demo steps, {len(d['seg_start'])} segments, "
          f"weight={args.weight} kl_coef={args.kl_coef} lr={args.lr}")

    w = compute_weights(frozen, d, obs, rtg, args.weight, args.beta,
                        args.wmax, device)
    pos = w > 0
    fork = th.as_tensor(d["is_fork"], dtype=th.bool, device=device)
    print(f"[sil] positively-weighted steps: {int(pos.sum())}/{n} "
          f"({100*pos.float().mean():.1f}%)  fork steps: {int(fork.sum())} "
          f"({100*fork.float().mean():.1f}%)")

    m0_f = action_match(model, obs, actions, fork)
    m0_nf = action_match(model, obs, actions, ~fork)
    print(f"[sil] action-match before: fork {100*m0_f:.1f}% (expect ~0), "
          f"non-fork {100*m0_nf:.1f}% (expect ~100)")

    # Optimize the policy network only; the value head stays frozen-by-construction
    # (BC/KL grads never reach vf params in SB3's separate-net MlpPolicy).
    model.policy.set_training_mode(True)
    optim = th.optim.Adam(
        [p_ for p_ in model.policy.parameters() if p_.requires_grad], lr=args.lr)

    for epoch in range(1, args.epochs + 1):
        perm = th.randperm(n, device=device)
        tot_bc, tot_kl, nb = 0.0, 0.0, 0
        for i in range(0, n, args.batch_size):
            j = perm[i:i + args.batch_size]
            dist = model.policy.get_distribution(obs[j])
            logp = dist.log_prob(actions[j])
            with th.no_grad():
                fdist_t = frozen.policy.get_distribution(obs[j]).distribution
            kl = th.distributions.kl_divergence(fdist_t, dist.distribution).mean()
            bc = -(w[j] * logp).mean()
            loss = bc + args.kl_coef * kl
            optim.zero_grad()
            loss.backward()
            th.nn.utils.clip_grad_norm_(model.policy.parameters(), args.max_grad_norm)
            optim.step()
            tot_bc += float(bc.detach()); tot_kl += float(kl.detach()); nb += 1

        m_f = action_match(model, obs, actions, fork)
        m_nf = action_match(model, obs, actions, ~fork)
        print(f"  epoch {epoch:>2}/{args.epochs}: bc={tot_bc/nb:+.4f}  "
              f"kl={tot_kl/nb:.4f}  fork-match {100*m_f:.1f}%  "
              f"non-fork {100*m_nf:.1f}%", flush=True)
        model.save(f"{args.out}_ep{epoch}")

    model.save(args.out)
    print(f"[sil] saved {args.out}.zip (+ per-epoch snapshots) — "
          f"eval with HCR_PER_WHEEL=1 eval.py --ab vs the champion")


if __name__ == "__main__":
    main()
