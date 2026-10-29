# Third-party notices

The repository's MIT licence covers this project's own source and documentation, not its dependencies or hosted services.

Runtime dependencies are declared in requirements.txt; build/development dependencies are in requirements-dev.txt and native/requirements-build.txt. Original dependency licence texts and metadata must be retained in distributions.

The native distribution dynamically links Qt 6 and OpenCascade 7.8.1 and includes Python 3.11 and the CAD/API Python dependencies. Qt and OCCT licence texts/exceptions are retained in licences/qt and licences/occt. Python packages retain their notices. Buildable application source and build scripts are included.

PyJWT, cryptography, Trimesh, SciPy and Pillow retain their upstream licence terms. Exact versions/licences are governed by installed package metadata. NSIS compiles the installer. Codex is installed separately by the user. OpenAI terms and eligible plan/API usage are independent of the repository licence; no inference key or credentials are bundled.

The monochrome UI icons are original geometric vector drawings. Public CAD references informed the design; no CADAM source or proprietary CAD implementation was copied. No image-generation service, model weights, Claude runtime or commercial CAD translator is included.
