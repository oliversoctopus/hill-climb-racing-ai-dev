"""Export a trained SB3 PPO policy to ONNX for browser inference.

ONNX captures only the policy network — argmax over the action logits gives the
action in deployment. The browser side has to construct the obs vector itself
(see web/index.html) since obs comes from the simulation, not from a Python env.

Usage:
    python export_onnx.py <checkpoint.zip> [output.onnx]

With no output path, exports straight to the browser deployment location
(web/ai_policy.onnx) — hard-refresh the served page to pick it up.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# The browser build lives in <repo_root>/web/; the deployed model is web/ai_policy.onnx.
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
DEPLOY_ONNX = os.path.join(REPO_ROOT, "web", "ai_policy.onnx")

from stable_baselines3 import PPO


class OnnxablePolicy(torch.nn.Module):
    """Wraps an SB3 PPO policy so torch.onnx.export can trace just the
    inference path. Skips the value head — deployment only needs actions."""

    def __init__(self, mlp_extractor: torch.nn.Module, action_net: torch.nn.Module):
        super().__init__()
        self.mlp_extractor = mlp_extractor
        self.action_net = action_net

    def forward(self, observation: torch.Tensor) -> torch.Tensor:
        # mlp_extractor returns (policy_hidden, value_hidden) for separate-net
        # config (which we use). For a single shared net, the API differs but
        # the same first-element extraction works.
        policy_hidden, _ = self.mlp_extractor(observation)
        return self.action_net(policy_hidden)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", help="Path to .zip PPO model")
    parser.add_argument("output", nargs="?", default=None,
                        help="Output .onnx path (default: web/ai_policy.onnx, the "
                             "browser deployment location)")
    args = parser.parse_args()

    if args.output is None:
        args.output = DEPLOY_ONNX

    # Make sure the target directory exists (web/ always does, but a custom path
    # might not) so torch.onnx.export doesn't fail on a missing folder.
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    print(f"[onnx] loading {args.checkpoint}")
    model = PPO.load(args.checkpoint, device="cpu")
    policy = model.policy

    print(f"[onnx] obs space: {policy.observation_space.shape}")
    print(f"[onnx] action space: {policy.action_space}")
    print(f"[onnx] mlp_extractor: {policy.mlp_extractor}")
    print(f"[onnx] action_net: {policy.action_net}")

    onnx_policy = OnnxablePolicy(policy.mlp_extractor, policy.action_net).eval()

    # Sanity: same output as the loaded model.
    obs_shape = policy.observation_space.shape
    dummy = torch.zeros(1, *obs_shape, dtype=torch.float32)
    with torch.no_grad():
        ref_logits = onnx_policy(dummy).cpu().numpy()
    print(f"[onnx] dummy logits: {ref_logits}")

    print(f"[onnx] exporting -> {args.output}")
    # dynamo=False uses the legacy TorchScript-based exporter, which produces
    # ONNX files compatible with older runtimes (incl. ONNX Runtime Web 1.18+).
    # The new dynamo exporter (PyTorch 2.x default) emits ops that ORT Web
    # doesn't always support, causing "Lt[m] is not a function" at load time.
    torch.onnx.export(
        onnx_policy,
        dummy,
        args.output,
        opset_version=11,
        input_names=["observation"],
        output_names=["action_logits"],
        dynamic_axes={"observation": {0: "batch"}, "action_logits": {0: "batch"}},
        dynamo=False,
    )

    # Verify it loads with onnxruntime and gives the same answer.
    try:
        import onnxruntime as ort
    except ImportError:
        print("[onnx] (skipping verification — onnxruntime not installed; install it to verify)")
        return

    sess = ort.InferenceSession(args.output, providers=["CPUExecutionProvider"])
    out = sess.run(None, {"observation": dummy.numpy().astype(np.float32)})[0]
    print(f"[onnx] onnxruntime logits: {out}")
    diff = float(np.max(np.abs(out - ref_logits)))
    print(f"[onnx] max diff: {diff:.2e}")
    if diff < 1e-4:
        print("[onnx] OK — torch and onnxruntime agree to <1e-4")
    else:
        print("[onnx] WARNING — significant divergence")


if __name__ == "__main__":
    main()
