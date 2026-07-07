"""What's keeping the chassis from settling? Isolate by varying each source
of continuous energy / damping and watch the post-throttle behavior."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tune import run_trace, score
import json

target = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'trace_js.json')))

def kinetic_energy_in_window(trace, start, end):
    """Sum of squared chassis velocities + angular vel over window — proxy for how much oscillation is still happening."""
    s = 0.0
    for t in trace[start:end]:
        s += t['cvx']**2 + t['cvy']**2 + t['comega']**2 * 0.5
    return s / (end - start)

# Baseline: tuner's best values
mr, mf, wf, sf, sd, ad = 824.98, 413.74, 0.77, 72.06, 38.69, 0.098
base = run_trace(mr, mf, wf, sf, sd, ad)
print(f'{"variant":<48} {"score":>8} {"settle_KE":>10} {"final cangle":>14} {"final omega":>14}')
print('-' * 100)

def show(label, t):
    ke = kinetic_energy_in_window(t, 100, 150)  # last 50 ticks (post-settling phase if it exists)
    print(f'{label:<48} {score(t, target):>8.1f} {ke:>10.4f} {t[-1]["cangle"]:>14.3f} {t[-1]["comega"]:>14.3f}')

show('JS reference                                  ', target)
show('Python tuned (baseline)                       ', base)

# Test 1: zero spring entirely (rigid suspension)
t = run_trace(mr, mf, wf, 0.0, 0.0, ad)
show('  + suspension rigid (freq=0, damp=0)         ', t)

# Test 2: gentle critically-damped spring
t = run_trace(mr, mf, wf, 10.0, 1.0, ad)
show('  + gentle spring (freq=10, damp=1)            ', t)

# Test 3: kill the motor's continuous torque (cap to 50)
t = run_trace(50, 25, wf, sf, sd, ad)
show('  + motor torque tiny (50/25)                  ', t)

# Test 4: high chassis angular damping
t = run_trace(mr, mf, wf, sf, sd, 1.0)
show('  + chassis ang_damp=1.0                       ', t)

# Test 5: zero friction (wheel spins free, no propulsion at all)
t = run_trace(mr, mf, 0.0, sf, sd, ad)
show('  + zero wheel friction                        ', t)
