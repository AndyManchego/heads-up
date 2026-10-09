# Heads Up: bills moving through Congress

Every morning this project:
1. Pulls bills with new activity from the official Congress.gov API.
2. Keeps only bills that are moving (passed the House or Senate, sent to the President, became law, or scheduled for a vote).
3. Writes a plain-English summary of each with Claude.
4. Saves them to a database that the website reads.

## Files
- `fetch_bills.py` is the daily script (fetch, filter, summarize, save).
- `schema.sql` creates the database table.
- `.github/workflows/daily.yml` runs the script every morning on GitHub, for free.
- `docs/index.html` is the website people visit.

## Setup (about 30 minutes, one time)

### 1. Get a Congress.gov API key
Sign up at https://api.data.gov/signup/ . The key arrives by email.

### 2. Get your Anthropic API key
At https://console.anthropic.com go to API Keys and create one. Copy it somewhere safe; you only see it once.

### 3. Set up the database (Supabase)
1. Create a free account at https://supabase.com and click New project.
2. Open SQL Editor, paste everything from `schema.sql`, and click Run.
3. Open Project Settings > API and copy three things:
   - Project URL
   - `anon` public key (safe to put in the website)
   - `service_role` secret key (NEVER put this in the website)

### 4. Put the code on GitHub
1. Create a free account at https://github.com and click New repository (name it `heads-up`).
2. Upload all these files, keeping the folders (`.github/workflows/` and `docs/`).
   Tip: the `.github` folder is hidden on Mac. Press Cmd+Shift+. in Finder to see it.

### 5. Add your secret keys to GitHub
In the repo: Settings > Secrets and variables > Actions > New repository secret. Add four:

| Name | Value |
|---|---|
| `CONGRESS_API_KEY` | from step 1 |
| `ANTHROPIC_API_KEY` | from step 2 |
| `SUPABASE_URL` | Project URL from step 3 |
| `SUPABASE_SERVICE_KEY` | `service_role` key from step 3 |

### 6. Run it the first time
Go to Actions > Daily bill update > Run workflow. Enter `14` for days to fill in the last two weeks.
Watch the log; each moving bill prints a line. After that it runs on its own every morning.

### 7. Turn on the website
1. Open `docs/index.html` on GitHub, click the pencil, and replace `SUPABASE_URL` and `SUPABASE_ANON_KEY` at the top of the script with your Project URL and **anon** key. Commit.
2. Settings > Pages > Source: Deploy from a branch > branch `main`, folder `/docs` > Save.
3. In a minute or two your site is live at `https://YOUR-USERNAME.github.io/heads-up/`.

## Costs
- GitHub, Supabase, Congress.gov: free at this size.
- Claude API: billed per use. Each run summarizes at most 40 bills (change `MAX_SUMMARIES`), and only new or changed bills get re-summarized. Set a monthly spending limit in the Anthropic console to be safe.

## Tweaks
- Run time: edit the `cron` line in `daily.yml` (it's in UTC).
- Model: set a `CLAUDE_MODEL` env var in `daily.yml`.
- Which stages count as "moving": edit `STAGES` in `fetch_bills.py`.
