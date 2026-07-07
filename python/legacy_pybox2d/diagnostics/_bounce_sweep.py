"""Can we push the front-wheel/chassis bouncing down to JS level by cranking suspension damping?"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from tune import run_trace, score
from compare import load

js = load("trace_js.json")
n = len(js)

def path_len(trace, key, start=30):
    return sum(abs(trace[t+1][key] - trace[t][key]) for t in range(start, n-1))

js_cy   = path_len(js, "cy")
js_w0y  = path_len(js, "w0y")
js_w1y  = path_len(js, "w1y")
js_ang  = path_len(js, "cangle")
print(f"JS bounce paths   : cy={js_cy:.1f}  w0y={js_w0y:.1f}  w1y={js_w1y:.1f}  cangle={js_ang:.3f}")
print()

# Sweep susp_damp keeping the other 7 params at their tuned values
mr, mf, wf, sf, _sd, ad, ld, wad = 834, 419, 0.75, 76.5, 39, 0.50, 0.37, 0.99
print(f"{'susp_damp':>10}  {'cy path':>8}  {'w0y path':>8}  {'w1y path':>8}  {'ang path':>8}  {'score':>8}")
for sd in [10, 25, 39, 60, 90, 130, 200]:
    t = run_trace(mr, mf, wf, sf, sd, ad, ld, wad)
    print(f"{sd:>10.1f}  {path_len(t,'cy'):>8.1f}  {path_len(t,'w0y'):>8.1f}  {path_len(t,'w1y'):>8.1f}  {path_len(t,'cangle'):>8.3f}  {score(t, js):>8.1f}")
