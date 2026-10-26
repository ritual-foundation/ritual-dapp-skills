# SVG Verification Protocol

This protocol prevents broken SVG rendering in GitHub README previews and file views.

## Why This Exists

GitHub can fail to render SVGs when files contain:

- Invalid encoding (non-UTF-8 bytes)
- Illegal XML control characters
- Malformed XML
- Unsafe embedded tags/links

The repository now includes an automated verifier at `scripts/verify_svgs.py`.

## Protocol Steps

1. **Run local static verification**
   - `python3 scripts/verify_svgs.py`
   - Checks:
     - UTF-8 decoding
     - Illegal control bytes (`< 0x20` except tab/newline/carriage return)
     - XML parse correctness
     - Forbidden tags (`script`, `foreignObject`, `iframe`, `object`, `embed`)
     - Unsafe `href` values (external/network/script/file schemes)
     - README markdown image links are valid and complete for `assets/*.svg`

2. **Run browser smoke verification (render test)**
   - Serve repo: `python3 -m http.server 8765`
   - Open each file in a browser:
     - `http://127.0.0.1:8765/assets/system-flow.svg`
     - `http://127.0.0.1:8765/assets/skill-classes.svg`
     - `http://127.0.0.1:8765/assets/example-workflow.svg`
   - Confirm each renders visibly (no parser/error page).

3. **Optional remote verification (private repo safe)**
   - `python3 scripts/verify_svgs.py --check-remote --repo ritual-foundation/ritual-dapp-skills --ref <branch>`
   - Requires `gh` auth. Confirms each referenced SVG exists at that git ref.

4. **Commit gate**
   - Only commit README/SVG changes after steps 1 + 2 pass.
   - If rendering fails on GitHub:
     - Re-run step 1 to detect encoding/control-char regressions.
     - Check README uses markdown image links: `![...](assets/<name>.svg)`.

## Known Good Conventions

- Save SVG files as UTF-8.
- Use markdown image syntax in README (not HTML `<picture>` wrappers).
- Keep SVG self-contained and avoid external image references.
