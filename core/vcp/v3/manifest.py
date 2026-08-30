"""Machine-readable manifest for the accepted Fiber V3 production path."""


V3_ACCEPTED_FEATURES = (
    "package-1-contracts", "package-2-banded-structural", "package-3-native-collision",
    "package-4.3-native-planner", "package-5.1-fused-contacts", "package-6.1-dispatch",
    "v2.1-route-reuse", "v2.2-request-identity", "v2.3-shared-world", "v2.4-batch-world",
    "pin-surface-recovery", "owner-contact-localization", "containment-handling",
    "augmented-unilateral-contact", "infeasible-start-filter", "limiting-contact-injection",
    "hard-midpoint-span-sqp", "true-length-irls", "zero-curvature",
    "weak-reference-fidelity-0.01", "adaptive-node-spacing", "adaptive-proximal-sqp",
    "cached-native-loader", "reusable-contact-buffer", "vectorized-swept-segments",
    "deterministic-parallel-native-queries", "persistent-fused-native-session",
    "dynamic-indexed-ccd", "topology-shared-world-space-bvh-refit",
)


V3_REJECTED_MODULES = (
    "solver_p71", "solver_p72", "solver_p8", "solver_p81", "solver_p82",
    "solver_v25_branch2", "composite_sqp", "acceleration", "v3_experiment",
    "v3_joint_experiment", "v3_covariant_experiment", "v3_transverse_experiment",
    "v3_active_step_experiment",
)


V3_ACCEPTED_REFERENCE = {
    "name": "REG_ADAPTIVE_SPACING",
    "global_accepted_cap": 180,
    "curvature_weight": 0.0,
    "fidelity_scale": 0.01,
    "true_length_epsilon_ratio": 1.0e-4,
    "spacing_trigger_accepted": 4,
    "spacing_trigger_cv": 0.75,
    "spacing_weight_ratio": 0.5,
    "regularization_ratio": 1.0e-6,
}
