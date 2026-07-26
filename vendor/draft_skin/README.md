# Draft-skin worker dependencies

`manifest.json` locks the Windows x64 CPython 3.11 worker bundle by filename and
SHA-256. The wheel archives are the distributed artifacts from PyPI and retain
their upstream metadata and complete license files:

| Distribution | Version | License file in wheel |
| --- | ---: | --- |
| SciPy | 1.15.3 | `scipy-1.15.3.dist-info/LICENSE.txt` |
| scikit-image | 0.25.2 | `scikit_image-0.25.2.dist-info/LICENSE.txt` |
| NetworkX | 3.4.2 | `networkx-3.4.2.dist-info/LICENSE.txt` |
| Pillow | 11.2.1 | `pillow-11.2.1.dist-info/licenses/LICENSE` |
| imageio | 2.37.0 | `imageio-2.37.0.dist-info/LICENSE` |
| tifffile | 2025.5.10 | `tifffile-2025.5.10.dist-info/licenses/LICENSE` |
| packaging | 25.0 | `packaging-25.0.dist-info/licenses/` |
| lazy-loader | 0.4 | `lazy_loader-0.4.dist-info/LICENSE.md` |

The worker verifies every archive before extraction. Do not replace or edit a
wheel without updating the pinned checksum and reviewing its license metadata.
