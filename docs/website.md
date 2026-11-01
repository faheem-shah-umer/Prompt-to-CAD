# Static project website

The buildless site is under `site/`. It uses local HTML/CSS/JavaScript, original application branding and approved synthetic app captures. No external fonts, trackers, cookies, analytics or backend are required. All asset/navigation paths inside the site are relative; the GitHub Pages project subpath is `/Prompt-to-CAD/`.

## Preview and checks

```powershell
python -m tools.prepare_site
python -m tools.check_links
python -m http.server 8080 --bind 127.0.0.1 --directory site-preview
```

Open `http://127.0.0.1:8080/Prompt-to-CAD/`. Test desktop and narrow widths, the Dark/Light screenshot buttons, Tab focus, anchor links, reduced-motion/forced-color settings, and missing images. A narrow desktop window is not proof of touch behavior on a physical phone.

For a repeatable browser check, optionally install Node 22+ and use an already installed Chrome or Edge:

```powershell
node tools/check_website.mjs
```

The script starts an isolated browser profile and loopback server, checks six widths from 320 to 1920 px, text contrast on the site's solid backgrounds, overflow, image/alt presence, keyboard skip navigation and screenshot switching. It saves private review captures/results under ignored `artifacts/website-review/` and stops its owned browser/server. Set `CAD_BROWSER` if your browser is installed elsewhere. It does not download a browser or access an existing profile.

## Visual system

The website maps the native app's existing semantic palette to a presentation surface: near-black base, separated neutral surfaces, purple actions/links and cyan focus. It uses locally available system fonts, a 12 px minimum for meaningful metadata, 17 px reading text, responsive headings, generous section spacing and 8/12 px control/card radii. Screenshots carry the product's actual design; no CADAM assets or layout identity are copied. There is no entrance animation or automatic screenshot carousel. Screenshot switching is immediate; the page honors reduced motion and keeps text selectable.

## GitHub Pages

`.github/workflows/pages.yml` is a manual deployment workflow. It validates local links, prepares the static artifact and targets the `github-pages` environment. Configure that environment with required reviewers before first deployment. No website secret variables are needed; deployment uses GitHub's standard short-lived workflow permissions.

The site is a source-project overview with setup, architecture and license links. It offers no binary download or contribution program. Hosting remains manual; repository visibility is unchanged.
