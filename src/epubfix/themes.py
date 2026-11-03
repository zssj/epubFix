"""Built-in typography themes."""

NOVEL_CSS = """@charset "utf-8";
/* epubfix novel theme v1 — generated, do not edit inside the book */

html {
  font-size: 100%;
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}

body {
  margin: 0;
  padding: 0;
  font-family: "Noto Serif CJK SC", "Source Han Serif SC", "Songti SC", "STSong", "SimSun", serif;
  font-size: 1em;
  line-height: 1.75;
  color: #1a1a1a;
  text-align: justify;
  text-justify: inter-ideograph;
  word-wrap: break-word;
  overflow-wrap: break-word;
  widows: 2;
  orphans: 2;
}

p {
  margin: 0.32em 0;
  padding: 0;
  text-indent: 2em;
  line-height: 1.75;
  text-align: justify;
  text-justify: inter-ideograph;
}

/* ---------- headings ---------- */

h1, h2, h3, h4, h5, h6 {
  margin: 1.2em 0 0.9em;
  padding: 0;
  text-indent: 0;
  text-align: center;
  font-weight: bold;
  line-height: 1.4;
  page-break-after: avoid;
  break-after: avoid;
}

h1 {
  font-size: 1.75em;
  margin: 2.2em 0 1.6em;
  letter-spacing: 0.04em;
}

h2 {
  font-size: 1.32em;
  margin: 2.4em 0 1.4em;
  letter-spacing: 0.06em;
}

h3 {
  font-size: 1.12em;
  margin: 1.4em 0 0.8em;
  text-align: left;
}

h4, h5, h6 {
  font-size: 1em;
  text-align: left;
}

/* A heading at the top of its own file must not force an extra blank page. */
.chapter {
  page-break-before: always;
  break-before: page;
}

.chapter.first,
h1.first,
h2.first,
h3.first {
  page-break-before: auto;
  break-before: auto;
}

.subtitle {
  margin: 0.8em 0 1.4em;
  text-indent: 0;
  text-align: center;
  font-size: 0.95em;
  line-height: 2;
  font-family: "KaiTi", "STKaiti", "Kaiti SC", serif;
}

/* ---------- verse / quotes ---------- */

.poem,
p.poem,
.poetry {
  margin: 0.18em 0;
  text-indent: 0;
  text-align: center;
  line-height: 2;
  font-family: "KaiTi", "STKaiti", "Kaiti SC", "Noto Serif CJK SC", serif;
}

blockquote,
.quote {
  margin: 1em 1.6em;
  padding: 0;
  text-indent: 0;
  font-size: 0.95em;
  line-height: 1.7;
  color: #333333;
}

blockquote p,
.quote p {
  text-indent: 0;
}

/* ---------- alignment helpers ---------- */

.center,
p.center,
div.center {
  text-indent: 0;
  text-align: center;
}

.right,
p.right,
div.right {
  text-indent: 0;
  text-align: right;
}

.left {
  text-indent: 0;
  text-align: left;
}

/* ---------- images ---------- */

img {
  max-width: 100%;
  height: auto;
  border: 0;
}

svg {
  max-width: 100%;
  border: 0;
}

.image,
div.image,
p.image,
figure {
  margin: 1em 0;
  padding: 0;
  text-indent: 0;
  text-align: center;
  page-break-inside: avoid;
  break-inside: avoid;
}

figure img,
.image img {
  display: block;
  margin: 0 auto;
}

figcaption,
.caption {
  margin: 0.4em 0 0.8em;
  text-indent: 0;
  text-align: center;
  font-size: 0.82em;
  line-height: 1.6;
  color: #555555;
}

/* ---------- lists / tables / rules ---------- */

ul, ol {
  margin: 0.6em 0 0.6em 1.6em;
  padding: 0;
}

li {
  text-indent: 0;
  line-height: 1.7;
}

table {
  width: 100%;
  margin: 1em 0;
  border-collapse: collapse;
  font-size: 0.9em;
}

th, td {
  padding: 0.35em 0.5em;
  border: 1px solid #cccccc;
  text-indent: 0;
  text-align: left;
}

hr {
  height: 0;
  margin: 1.4em 0;
  border: 0;
  border-top: 1px solid #cccccc;
}

/* ---------- links / footnotes ---------- */

a {
  color: inherit;
  text-decoration: none;
}

a[epub|type~="noteref"],
.noteref {
  vertical-align: super;
  font-size: 0.72em;
  line-height: 0;
}

aside[epub|type~="footnote"],
.footnote {
  margin: 0.8em 0;
  padding: 0.5em 0.7em;
  text-indent: 0;
  font-size: 0.82em;
  line-height: 1.6;
  color: #444444;
  border-left: 2px solid #cccccc;
}

/* ---------- cover ---------- */

body.cover,
.cover {
  margin: 0;
  padding: 0;
  text-align: center;
  text-indent: 0;
}

body.cover img,
.cover img {
  max-width: 100%;
  max-height: 100%;
}

/* ---------- dark mode (readers that support it) ---------- */

@media (prefers-color-scheme: dark) {
  body { color: #d8d8d8; }
  blockquote, .quote { color: #c4c4c4; }
  figcaption, .caption { color: #b0b0b0; }
  aside[epub|type~="footnote"], .footnote {
    color: #c0c0c0;
    border-left-color: #555555;
  }
  th, td { border-color: #555555; }
  hr { border-top-color: #555555; }
}
"""

THEMES = {"novel": NOVEL_CSS}
