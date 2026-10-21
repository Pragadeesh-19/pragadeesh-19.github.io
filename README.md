# The blog: set up, write, publish

This folder is a complete blog. You write essays as Markdown files, one command turns them into a static website, and
GitHub Pages serves that website for free at `https://pragadeesh-19.github.io/`.

There is no server, no database and no JavaScript. The only moving part is `build.py`.

## What is in this folder

| Path | What it is | Do you edit it? |
|---|---|---|
| `content/posts/` | One Markdown file per essay | Yes, this is where you write |
| `content/pages/intro.md` | The two short paragraphs at the top of the home page | Sometimes |
| `content/pages/about.md` | The About page | Sometimes |
| `static/` | The stylesheet, the icon and images (`static/img/`) | When you add images |
| `site.json` | Blog title, your name, the site address | Rarely |
| `build.py` | Turns `content/` and `static/` into `docs/` | No |
| `docs/` | **The finished website.** GitHub Pages serves this folder | Never by hand. `build.py` rewrites it |
| `requirements.txt` | The two Python packages the builder needs | No |

The one rule: **edit `content/` and `static/`, run `build.py`, and commit everything including `docs/`.**

---

## Part 1: Run it on your computer first (5 minutes)

You need Python 3.10 or newer and Git. Both are already on this machine.

1. Open a terminal in this folder.
   - Windows: open the folder in File Explorer, click the address bar, type `powershell`, press Enter.
2. Install the two packages the builder uses (one time only):

   ```sh
   python -m pip install -r requirements.txt
   ```

3. Preview the site, including unfinished drafts:

   ```sh
   python build.py preview
   ```

   It prints `Preview at http://127.0.0.1:8000/`. Open that address in your browser. You should see the home page, with
   the essay listed under "Writing". Press `Ctrl+C` in the terminal to stop it.

If you see an error instead, read the line that starts with `ERROR:`. It names the file and says what to fix.

---

## Part 2: Put it on the internet with GitHub Pages (15 minutes, one time)

### Step 1. Create the repository

1. Go to <https://github.com/new> (you are logged in as `Pragadeesh-19`).
2. **Repository name:** type exactly `pragadeesh-19.github.io`

   > It must be **all lowercase**, even though your username has a capital P. GitHub's documentation says: "if your
   > user or organization name contains uppercase letters, you must lowercase the letters." A name that does not match
   > exactly never becomes a website.

3. Choose **Public**. On a free GitHub plan, Pages only works for public repositories.
4. **Leave all three boxes unticked** (Add a README, Add .gitignore, Choose a license). The folder already has what it needs.
5. Click **Create repository**. You land on a page of setup instructions. Ignore them and use Step 2.

### Step 2. Upload this folder

Open a terminal in this folder (same trick as in Part 1) and run these commands one at a time:

```sh
git init -b main
git add .
git commit -m "Start the blog"
git remote add origin https://github.com/Pragadeesh-19/pragadeesh-19.github.io.git
git push -u origin main
```

What each line does: the first four make a Git history of this folder and tell it where the GitHub repository is. The
last one uploads it. If a login window or browser tab opens, sign in to GitHub and approve it.

**Check it worked:** refresh `https://github.com/Pragadeesh-19/pragadeesh-19.github.io`. You should see these files,
including a `docs` folder. Open `docs`: it must contain `index.html`. If `docs` is missing, you skipped
`git add .`: run `git add .`, then `git commit -m "Add the built site"`, then `git push`.

> **Email privacy.** Every commit records the email address from your Git settings, and a public repository shows it.
> To keep your real address private, use the one GitHub gives you: on github.com open **Settings, then Emails**, tick
> **Keep my email addresses private**, copy the `...@users.noreply.github.com` address shown there, and run
> `git config user.email "that-address"` in this folder before your first commit. (Commits you already made in the
> NodusDB repository already show your address; this only protects the new blog.)

### Step 3. Turn on GitHub Pages

1. In the repository, click the **Settings** tab (the far right of the row under the repository name).
2. In the left sidebar, under **Code, planning, and automation**, click **Pages**.
3. Under **Build and deployment**, find **Source** and choose **Deploy from a branch**.
4. Under **Branch**, choose **main** in the first dropdown and **/docs** in the second dropdown (it says `/ (root)` by
   default; change it to `/docs`).
5. Click **Save**.

### Step 4. Wait, then look

1. Click the **Actions** tab. A run called **pages build and deployment** appears. Wait for its green tick (usually 1 to
   3 minutes; GitHub says up to 10).
2. Open **<https://pragadeesh-19.github.io/>**. You should see your blog.
3. Go back to **Settings, then Pages**: it now says "Your site is live at ..." and has a tick box **Enforce HTTPS**.
   Make sure it is ticked.

### Step 5. Check it like a stranger would

- Open the home page, the About page and the essay on your phone, not only on the computer.
- Open `https://pragadeesh-19.github.io/feed.xml`. You should see XML text (that is the RSS feed).
- Paste the essay's address into LinkedIn's Post Inspector (<https://www.linkedin.com/post-inspector/>). It should show
  the title, the description and a picture. If the picture is wrong, fix `image:` in the essay's header and run the
  inspector again, because LinkedIn caches previews.

### If something is wrong

| What you see | What to do |
|---|---|
| "There isn't a GitHub Pages site here" or a GitHub 404 | Pages is not on yet, or the repository is private, or the name is not exactly `pragadeesh-19.github.io`. Re-check Steps 1 and 3. |
| The Actions tab shows a red cross | Click the run, then click the failed step and read the message. The usual cause is that `docs/` is missing from `main`. Run `python build.py`, then `git add .`, `git commit -m "Rebuild"`, `git push`. |
| The site is there but unstyled | The page was cached. Press `Ctrl+F5`. If it persists, make sure `docs/style.css` exists on GitHub. |
| You pushed a change and nothing changed | Wait for the green tick in the Actions tab, then press `Ctrl+F5`. |
| `git push` says "rejected" or "failed to push some refs" | Run `git pull --rebase origin main`, then `git push`. |
| `ModuleNotFoundError: No module named 'markdown_it'` | Run `python -m pip install -r requirements.txt`. |
| A link in the post points to the wrong place | Run `python build.py check`. It lists every broken link. |

---

## Part 3: Write and publish an essay

Each essay is one Markdown file in `content/posts/`.

1. Create a draft:

   ```sh
   python build.py new "The title of the essay"
   ```

   This creates `content/posts/2026-11-10-the-title-of-the-essay.md` with a header like this:

   ```
   ---
   title: The title of the essay
   date: 2026-11-10
   description: One or two sentences that say what a reader gets from this essay.
   slug: the-title-of-the-essay
   draft: true
   ---
   ```

   `description` is what appears under the title on the home page and in link previews on LinkedIn, Reddit and Slack,
   so write it carefully. `slug` becomes the web address: `/posts/the-title-of-the-essay/`. Optional: `image:
   /img/og-name.png` sets the link-preview picture (1200 by 630 pixels).

2. Write below the second `---` line, in Markdown:

   - `## A heading` and `### A smaller heading`
   - `**bold**`, `*italic*`, `` `code` ``, `[link text](https://example.com)`
   - A code block starts with three backticks and the language, for example ` ```java `, and ends with three backticks.
   - A table has a header row, a `|---|---|` row, then the rows.
   - An image: put the file in `static/img/` and write `![What the picture shows](/img/name.png)`.

3. See it: `python build.py preview`, then open `http://127.0.0.1:8000/posts/your-slug/`. Drafts show in preview only.

4. When it is ready, **delete the `draft: true` line** (or change it to `draft: false`). Update `date:` to the day you
   publish.

5. Run the safety check:

   ```sh
   python build.py check
   ```

   It rebuilds the site and checks every link, every heading anchor, the RSS feed and the sitemap. It also **refuses to
   publish** a post that still contains `[link to`, the words `TODO` or `FIXME`, or an em dash, so you cannot ship a
   half-finished placeholder by accident.

6. Publish:

   ```sh
   git add .
   git commit -m "Publish: the title of the essay"
   git push
   ```

   The Actions tab shows the deploy. The essay is live within a few minutes.

---

## Part 4: See whether anyone reads it

GitHub Pages gives you no visitor numbers. Use these free ones:

- **Where people come from.** On the NodusDB repository, open **Insights, then Traffic**. It shows visitors, clones and
  the top referring sites for the last 14 days. Check it daily in launch week and write the numbers down, because GitHub
  forgets after 14 days.
- **Downloads.** <https://pypistats.org/packages/nodusdb> shows PyPI downloads per day. Many early numbers are mirrors
  and bots, so watch the trend, not the total.
- **Blog visitors (optional).** A privacy-friendly counter such as GoatCounter (<https://www.goatcounter.com>, free for
  personal sites) gives page views per essay and referrers without cookies. Sign up, copy the one `<script>` line it
  gives you, and put it in `site.json` as `"analytics_snippet": "<script ...></script>"`. Run `python build.py`, commit
  and push.

---

## Part 5: Later, a custom domain (optional)

The free address is fine for now, and it keeps working if you add a domain later.

1. Buy a domain from any registrar.
2. In `site.json`, set `"custom_domain": "yourname.com"` and change `"base_url"` to `"https://yourname.com"`. Run
   `python build.py`, commit and push. This writes a `docs/CNAME` file.
3. At the registrar, add DNS records. For the bare domain, four `A` records pointing to `185.199.108.153`,
   `185.199.109.153`, `185.199.110.153` and `185.199.111.153`. For `www`, one `CNAME` record pointing to
   `pragadeesh-19.github.io`. (These are the addresses in GitHub's documentation. Check
   <https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site> before you use them in
   case they have changed.)
4. In **Settings, then Pages**, type the domain under **Custom domain** and tick **Enforce HTTPS** once it is allowed.

---

## Two rules while you are on a Student visa

- Keep the blog free to read. **Do not turn on ads, paid subscriptions, sponsorships or GitHub Sponsors.** Income from
  any of those is business activity, which the Student visa does not allow. Check with your university's international
  student advice team before you change this.
- The blog is allowed to describe NodusDB. It is not allowed to sell anything or run a company on your behalf.
