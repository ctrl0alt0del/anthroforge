# Pinned native dependencies

Unmodified headers used by the production height-smoothing target:

- Eigen **3.4.0**, `Eigen/`, MPL-2.0; `MPL-2.0.txt`.
  https://eigen.tuxfamily.org/
- PIQP **0.6.4**, `piqp/`, BSD-2-Clause; `PIQP-LICENSE`.
  https://github.com/PREDICT-EPFL/piqp/releases/tag/v0.6.4
- libigl **2.6.0**, `igl/`, MPL-2.0; `MPL-2.0.txt`.
  https://github.com/libigl/libigl/releases/tag/v2.6.0
  Only the local include closure of cotmatrix and massmatrix is included.

`manifest.json` records SHA-256 of the imported headers and license files.
Builds define EIGEN_MPL2_ONLY. No runtime Python package or BLASFEO dependency is
required. Do not apply the project's function-length rule to these upstream
headers or edit them to tune the algorithm; adapt through the maintained core.
