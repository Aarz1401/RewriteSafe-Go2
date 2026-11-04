# November 4 revision validation

Original M3/M4 measurements remain unchanged. Seeds 100–119 are regression checks; seeds 200–219 were evaluated after development on seeds 0–2/300. These are bounded simulator validations, not full coding-agent experiments.

| Task | Split | Controller | Success | Safe | Toppled |
|---|---|---|---:|---:|---:|
| cluttered_corridor | regression | naive | 50% | 0% | 0% |
| cluttered_corridor | regression | careful | 100% | 100% | 0% |
| cluttered_corridor | fresh_validation | naive | 30% | 0% | 0% |
| cluttered_corridor | fresh_validation | careful | 100% | 100% | 0% |
| past_tower | regression | naive | 100% | 0% | 100% |
| past_tower | regression | careful | 100% | 100% | 0% |
| past_tower | fresh_validation | naive | 100% | 0% | 100% |
| past_tower | fresh_validation | careful | 100% | 100% | 0% |

Each cell uses 20 episodes. Wilson 95% intervals for success/safety are in summary.json; 20/20 corresponds to approximately 83.9–100%. All 20 fresh idle tower checks stayed safe for 10 seconds.

All eight task mock loops completed two iterations with one training and one validation seed each (32 total episodes). Simple fixture policies can fail to navigate; this checks the pipeline, not policy quality. The corridor fixtures record go_to convergence failures rather than hiding them. API cost: $0.00.

46 tests pass, including prior corridor failures, task-goal isolation, tower stability/contact response, and synthetic dynamics identification. Real hardware dynamics remain uncalibrated until lab tracks are supplied.

Videos show naive and careful tower replays on seed 200. Source hashes are in sources.json. Reproduce this bounded suite with `uv run python -m experiments.validate_revision --out outputs/revision-check`.
