# Span-SQP seed into GCP

This rejected the complete SQP-v2 stage experiment and tests one narrow composition only:

1. run corrected span-SQP to its validated result;
2. pass those exact points to GCP as its initial state;
3. keep the same hard-span partition, fixed structural reference, clearance, owner policy, CCD,
   and final static validator;
4. compare the input seed with the GCP result.

This is an isolated benchmark and render tool. It is not imported by the production facade and
does not change engine selection or publication behavior.

The fixed configuration is GCP force ratio `0.1`; the command-line accepted cap is shared by the
span-SQP seed solve and proportionally divided across GCP spans. Reported timing separates the
seed solve, GCP-only refinement, and the complete serial pipeline.

## Fiber_2 result

Read-only input: `fiber_sphere.blend/FIBER_2`, SHA-256
`D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

| Measurement | span-SQP seed | span-SQP then GCP |
|---|---:|---:|
| Validated | yes | yes |
| Worst free-node turn | 22.7095° | 22.7103° |
| Free-turn p95 | 10.8023° | 10.8021° |
| Path length | 20.392520 | 20.392438 |
| Serial time, median | 345.7 ms | 438.9 ms |

GCP alone took 91.6 ms median, accepted 12 steps, rejected one, and moved any node by at most
`0.00006104` world units. It therefore converged effectively to the span-SQP seed and did not
remove the visible unevenness. This composition is rejected as a solver improvement.
