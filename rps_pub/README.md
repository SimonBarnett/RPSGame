# RPS web embed + PWA

Strategy JSON is the same tree as the Python sim. Learning (UCB, GP-EI, persist) lives only in Python. After each learn pass, `playbook.publish_to_js()` copies `strategies/*.json` into this folder. You can also copy `strategies/types/` here by hand — JS reads those files directly (`when.states`, `switch`, `movement`, `weights`, `base`, `stats` for greedy pick).

## AWS folder (installable app)

```
rps.js
index.html
manifest.webmanifest
sw.js
icons/icon-192.png
icons/icon-512.png
icons/apple-touch-icon.png
strategies/types/ROCK/
strategies/types/PAPER/
strategies/types/SCISSORS/
```

Open `https://YOUR_BUCKET/index.html` over HTTPS. Chrome / Safari will offer **Install app** / Add to Home Screen.

Service worker + manifest **must** be same-origin as that HTML. They cannot live only on a third-party embed page.

## Other site (HTML only)

```html
<div id="rps" style="position:fixed;inset:0"></div>
<script src="https://YOUR_BUCKET/rps.js"></script>
<script>RPS.mount("#rps");</script>
```

That page is not itself a PWA (no same-origin SW). Link users to the AWS `index.html` to install.

S3 CORS: allow GET/HEAD/OPTIONS from the embed origin if you fetch strategy JSON from that page.

Mobile: canvas fills the viewport; marble radius is 60% on coarse-pointer / narrow screens.
