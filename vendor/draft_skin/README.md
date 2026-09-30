# Draft-skin worker dependencies

`manifest.json` locks the Windows x64 CPython 3.11 source wheels and the exact
expanded bundle manifest by SHA-256. The tracked wheel archives are packaging
inputs from PyPI. The installed release carries the expanded files, including
upstream metadata and complete license files, but not duplicate wheel archives:

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

The offline builder checks wheel SHA-256, `RECORD` hashes/sizes, safe and unique
paths, and native modules. The worker only reads and hashes installed files;
it does not extract wheels, download files, or modify its dependency directory.
Do not replace a wheel without reviewing its license and bumping the bundle
version and lock explicitly. See `docs/draft_skin.md` for build and upgrade
instructions.
