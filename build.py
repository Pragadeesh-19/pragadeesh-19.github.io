import argparse
import datetime
import hashlib
import html
import http.server
import json
import re
import shutil
import socketserver
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

from markdown_it import MarkdownIt
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
STATIC = ROOT / "static"
OUT = ROOT / "docs"
SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
BASE = SITE["base_url"].rstrip("/")
FORBIDDEN_IN_POSTS = [r"\[link to", r"\bTODO\b", r"\bFIXME\b", "—"]


class BuildError(Exception):
    pass


def read_text(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def split_front_matter(path):
    text = read_text(path)
    if not text.startswith("---\n"):
        raise BuildError(f"{path.name}: the file must start with a --- front matter block")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise BuildError(f"{path.name}: the front matter block is not closed with ---")
    meta = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise BuildError(f"{path.name}: front matter line without a colon: {line!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip()] = value
    return meta, text[end + 5:]


def slugify(text):
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "section"


def highlight_code(code, language, attrs):
    try:
        lexer = get_lexer_by_name(language) if language else TextLexer()
    except ClassNotFound:
        lexer = TextLexer()
    spans = pygments_highlight(code, lexer, HtmlFormatter(nowrap=True))
    label = html.escape(language) if language else "text"
    return f'<pre class="code" data-language="{label}"><code>{spans}</code></pre>'


def heading_ids(state):
    used = set()
    tokens = state.tokens
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag in ("h2", "h3"):
            slug = slugify(tokens[index + 1].content)
            candidate, number = slug, 2
            while candidate in used:
                candidate = f"{slug}-{number}"
                number += 1
            used.add(candidate)
            token.attrSet("id", candidate)


def make_markdown():
    md = MarkdownIt("commonmark", {"html": True, "highlight": highlight_code})
    md.enable(["table", "strikethrough"])
    md.core.ruler.push("heading_ids", heading_ids)
    return md


MARKDOWN = make_markdown()


def render_markdown(body):
    out = MARKDOWN.render(body)
    out = re.sub(
        r'<h([23]) id="([^"]+)">(.*?)</h\1>',
        lambda m: f'<h{m.group(1)} id="{m.group(2)}">{m.group(3)}'
                  f'<a class="anchor" href="#{m.group(2)}" aria-label="Link to this section">#</a></h{m.group(1)}>',
        out,
        flags=re.S,
    )
    out = out.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    return out



def format_date(date):
    return f"{date.day} {date.strftime('%B %Y')}"


def load_posts(include_drafts):
    posts = []
    for path in sorted((CONTENT / "posts").glob("*.md")):
        meta, body = split_front_matter(path)
        for field in ("title", "date", "description", "slug"):
            if not meta.get(field):
                raise BuildError(f"{path.name}: front matter is missing '{field}'")
        draft = meta.get("draft", "false").lower() == "true"
        if draft and not include_drafts:
            continue
        try:
            date = datetime.date.fromisoformat(meta["date"])
        except ValueError:
            raise BuildError(f"{path.name}: date must look like 2026-11-10")
        if not re.fullmatch(r"[a-z0-9-]+", meta["slug"]):
            raise BuildError(f"{path.name}: slug may only contain a-z, 0-9 and dashes")
        if not draft:
            for forbidden in FORBIDDEN_IN_POSTS:
                if any(re.search(forbidden, text) for text in (body, meta["title"], meta["description"])):
                    raise BuildError(
                        f"{path.name}: found text that must not be published ({forbidden}). "
                        "Fix it, or keep the post as 'draft: true' until it is done."
                    )
        posts.append({
            "title": meta["title"],
            "date": date,
            "description": meta["description"],
            "slug": meta["slug"],
            "image": meta.get("image", SITE["default_image"]),
            "draft": draft,
            "body": body,
            "html": render_markdown(body),
            "path": f"/posts/{meta['slug']}/",
        })
    posts.sort(key=lambda p: p["date"], reverse=True)
    slugs = [p["slug"] for p in posts]
    if len(slugs) != len(set(slugs)):
        raise BuildError("two posts share the same slug")
    return posts


def absolute(path):
    return path if path.startswith("http") else BASE + path


def head(title, description, path, kind="website", image=None, published=None):
    full_title = title if title == SITE["title"] else f"{title} | {SITE['title']}"
    image_url = absolute(image or SITE["default_image"])
    page_url = absolute(path)
    article = f'<meta property="article:published_time" content="{published.isoformat()}">' if published else ""
    ld = {
        "@context": "https://schema.org",
        "@type": "BlogPosting" if published else "WebSite",
        "headline": title,
        "description": description,
        "url": page_url,
        "image": image_url,
        "author": {"@type": "Person", "name": SITE["author"]},
    }
    if published:
        ld["datePublished"] = published.isoformat()
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{html.escape(full_title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{page_url}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="alternate" type="application/atom+xml" title="{html.escape(SITE['title'])}" href="/feed.xml">
<link rel="stylesheet" href="/style.css?v={STYLE_HASH}">
<meta property="og:site_name" content="{html.escape(SITE['title'])}">
<meta property="og:type" content="{'article' if published else 'website'}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:url" content="{page_url}">
<meta property="og:image" content="{image_url}">
{article}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(title)}">
<meta name="twitter:description" content="{html.escape(description)}">
<meta name="twitter:image" content="{image_url}">
<script type="application/ld+json">{json.dumps(ld)}</script>"""


def layout(title, description, path, body, kind="website", image=None, published=None, active=""):
    def nav(label, href, key):
        current = ' aria-current="page"' if active == key else ""
        return f'<a href="{href}"{current}>{label}</a>'

    return f"""<!doctype html>
<html lang="{SITE.get('language', 'en')}">
<head>
{head(title, description, path, kind, image, published)}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
<div class="wrap header-row">
<a class="brand" href="/">{html.escape(SITE['title'])}</a>
<nav aria-label="Main">
{nav('Essays', '/', 'home')}
{nav('About', '/about/', 'about')}
<a href="{SITE['github']}">GitHub</a>
<a href="/feed.xml">RSS</a>
</nav>
</div>
</header>
<main id="main" class="wrap">
{body}
</main>
<footer class="site-footer">
<div class="wrap">
<p>{html.escape(SITE['author'])}, London. NodusDB is open source under the Apache License 2.0: <a href="{SITE['github']}">source</a>, <a href="{SITE['pypi']}">PyPI</a>.</p>
</div>
</footer>
{SITE.get('analytics_snippet', '')}
</body>
</html>
"""


def post_list(posts):
    if not posts:
        return "<p>The first essay is coming.</p>"
    items = []
    for post in posts:
        items.append(
            f'<li class="post-item"><a class="post-link" href="{post["path"]}">{html.escape(post["title"])}</a>'
            f'<p class="post-meta"><time datetime="{post["date"].isoformat()}">{format_date(post["date"])}</time></p>'
            f'<p>{html.escape(post["description"])}</p></li>'
        )
    return '<ul class="post-list">' + "".join(items) + "</ul>"


def build_home(posts):
    intro = render_markdown(read_text(CONTENT / "pages" / "intro.md"))
    body = f'<section class="intro">{intro}</section><h2 class="section-title">Essays</h2>{post_list(posts)}'
    return layout(SITE["title"], SITE["description"], "/", body, active="home")


def build_page(name, active):
    meta, body = split_front_matter(CONTENT / "pages" / f"{name}.md")
    content = render_markdown(body)
    page_html = f'<article class="post"><h1>{html.escape(meta["title"])}</h1>{content}</article>'
    return layout(meta["title"], meta["description"], f"/{name}/", page_html, active=active)


def build_post(post):
    article = (
        f'<article class="post"><header class="post-head"><h1>{html.escape(post["title"])}</h1>'
        f'<p class="post-meta">{html.escape(SITE["author"])}, <time datetime="{post["date"].isoformat()}">{format_date(post["date"])}</time></p></header>'
        f'{post["html"]}'
        f'<footer class="post-foot"><p>Corrections and questions are welcome as an '
        f'<a href="{SITE["github"]}/issues">issue on GitHub</a>.</p></footer></article>'
    )
    return layout(post["title"], post["description"], post["path"], article, "article", post["image"], post["date"])


def build_404():
    body = '<article class="post"><h1>Page not found</h1><p>That page does not exist. Try the <a href="/">list of essays</a>.</p></article>'
    return layout("Page not found", "That page does not exist.", "/404.html", body)


def absolutize(fragment):
    return re.sub(r'(href|src)="/(?!/)', lambda m: f'{m.group(1)}="{BASE}/', fragment)


def build_feed(posts):
    updated = (posts[0]["date"] if posts else datetime.date.today()).isoformat() + "T00:00:00Z"
    entries = []
    for post in posts:
        url = absolute(post["path"])
        entries.append(
            "<entry>"
            f"<title>{html.escape(post['title'])}</title>"
            f'<link href="{url}"/>'
            f"<id>{url}</id>"
            f"<updated>{post['date'].isoformat()}T00:00:00Z</updated>"
            f"<summary>{html.escape(post['description'])}</summary>"
            f'<content type="html">{html.escape(absolutize(post["html"]))}</content>'
            "</entry>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>{html.escape(SITE['title'])}</title>"
        f"<subtitle>{html.escape(SITE['description'])}</subtitle>"
        f'<link href="{BASE}/feed.xml" rel="self"/><link href="{BASE}/"/>'
        f"<id>{BASE}/</id><updated>{updated}</updated>"
        f"<author><name>{html.escape(SITE['author'])}</name></author>"
        + "".join(entries)
        + "</feed>\n"
    )


def build_sitemap(posts):
    urls = [(BASE + "/", None), (BASE + "/about/", None)] + [(absolute(p["path"]), p["date"]) for p in posts]
    rows = "".join(
        f"<url><loc>{loc}</loc>" + (f"<lastmod>{date.isoformat()}</lastmod>" if date else "") + "</url>"
        for loc, date in urls
    )
    return f'<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>\n'


def style_css():
    return (STATIC / "style.css").read_text(encoding="utf-8")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build(include_drafts=False):
    global STYLE_HASH
    css = style_css()
    STYLE_HASH = hashlib.sha1(css.encode("utf-8")).hexdigest()[:8]
    posts = load_posts(include_drafts)
    OUT.mkdir(exist_ok=True)
    for child in OUT.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    write(OUT / "style.css", css)
    for item in STATIC.iterdir():
        if item.name == "style.css":
            continue
        target = OUT / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    write(OUT / ".nojekyll", "")
    if SITE.get("custom_domain"):
        write(OUT / "CNAME", SITE["custom_domain"] + "\n")
    write(OUT / "index.html", build_home(posts))
    write(OUT / "about" / "index.html", build_page("about", "about"))
    for post in posts:
        write(OUT / "posts" / post["slug"] / "index.html", build_post(post))
    write(OUT / "404.html", build_404())
    write(OUT / "feed.xml", build_feed(posts))
    write(OUT / "sitemap.xml", build_sitemap(posts))
    write(OUT / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n")
    return posts


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.stack = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        for key in ("href", "src"):
            if values.get(key):
                self.links.append(values[key])
        if tag not in ("meta", "link", "img", "br", "hr", "input", "source"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ("meta", "link", "img", "br", "hr", "input", "source"):
            return
        if not self.stack or self.stack[-1] != tag:
            raise BuildError(f"unbalanced </{tag}>, expected </{self.stack[-1] if self.stack else 'nothing'}>")
        self.stack.pop()


def check():
    problems = []
    pages = sorted(OUT.rglob("*.html"))
    page_ids = {}
    for page in pages:
        collector = LinkCollector()
        try:
            collector.feed(page.read_text(encoding="utf-8"))
        except BuildError as error:
            problems.append(f"{page.relative_to(OUT)}: {error}")
            continue
        if collector.stack:
            problems.append(f"{page.relative_to(OUT)}: unclosed <{collector.stack[-1]}>")
        page_ids[page] = (collector.ids, collector.links)
    for page, (ids, links) in page_ids.items():
        for link in links:
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            target, _, fragment = link.partition("#")
            target = target.split("?")[0]
            if target == "":
                if fragment and fragment not in ids:
                    problems.append(f"{page.relative_to(OUT)}: missing anchor #{fragment}")
                continue
            local = OUT / target.lstrip("/")
            if local.is_dir():
                local = local / "index.html"
            if not local.exists():
                problems.append(f"{page.relative_to(OUT)}: broken link {link}")
    for xml_file in ("feed.xml", "sitemap.xml"):
        try:
            ET.parse(OUT / xml_file)
        except ET.ParseError as error:
            problems.append(f"{xml_file}: {error}")
    return problems


def new_post(title):
    slug = slugify(title)
    today = datetime.date.today().isoformat()
    path = CONTENT / "posts" / f"{today}-{slug}.md"
    if path.exists():
        raise BuildError(f"{path.name} already exists")
    write(path, f"---\ntitle: {title}\ndate: {today}\ndescription: One or two sentences that say what a reader gets from this essay.\nslug: {slug}\ndraft: true\n---\n\nWrite here.\n")
    return path


def serve(port):
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=str(OUT), **kwargs)
    with socketserver.TCPServer(("127.0.0.1", port), handler) as server:
        print(f"Preview at http://127.0.0.1:{port}/  (press Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description="Build the site into docs/.")
    sub = parser.add_subparsers(dest="command")
    build_cmd = sub.add_parser("build", help="build docs/ from content/ (the default)")
    build_cmd.add_argument("--drafts", action="store_true", help="include posts marked draft: true")
    preview = sub.add_parser("preview", help="build including drafts, then serve docs/ locally")
    preview.add_argument("--port", type=int, default=8000)
    new = sub.add_parser("new", help="create a new draft post")
    new.add_argument("title")
    check_cmd = sub.add_parser("check", help="build, then check every link and both XML files")
    check_cmd.add_argument("--drafts", action="store_true", help="include posts marked draft: true")
    args = parser.parse_args()
    try:
        if args.command == "new":
            print("Created", new_post(args.title))
            return 0
        posts = build(include_drafts=args.command == "preview" or getattr(args, "drafts", False))
        print(f"Built {len(posts)} post(s) into {OUT}")
        if args.command == "check":
            problems = check()
            for problem in problems:
                print("PROBLEM:", problem)
            print("check passed" if not problems else f"{len(problems)} problem(s)")
            return 1 if problems else 0
        if args.command == "preview":
            serve(args.port)
        return 0
    except BuildError as error:
        print("ERROR:", error)
        return 1


STYLE_HASH = "dev"

if __name__ == "__main__":
    sys.exit(main())
