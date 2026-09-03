# Community API (Cloudflare Worker)

GitHub sign-in, synced "My list" and community picks for scienceofplacebo.org. Free tier is ample (100k requests/day, 1 GB KV).

## One-time setup (about 10 minutes)

1. **GitHub OAuth App** (https://github.com/settings/developers → OAuth Apps → New):
   - Application name: Science of Placebo · Homepage: https://scienceofplacebo.org
   - Authorization callback URL: `https://community.scienceofplacebo.org/auth/callback`
   - Copy the Client ID; generate a Client Secret and copy it.
2. **Cloudflare**, from this folder:
   ```bash
   cd worker && npm install
   npx wrangler login                                  # opens the browser once
   npx wrangler kv namespace create STORE              # prints an id → paste into wrangler.jsonc ("id")
   # paste the GitHub Client ID into wrangler.jsonc ("GITHUB_CLIENT_ID")
   npx wrangler secret put GITHUB_CLIENT_SECRET        # paste the secret when prompted
   npx wrangler deploy                                 # creates community.scienceofplacebo.org (DNS is added automatically)
   ```
3. In `site/assets/config.js` set `communityApi: "https://community.scienceofplacebo.org"` and push.

The site then shows "Sign in with GitHub" on the Join and My list pages. Stars sync to the account, the browser list is merged in on first sign-in, and the Community picks page ranks the most-starred papers.

## Data and privacy
Stored per user: GitHub numeric id, login, avatar URL, list of paper ids, last update time. No email, no password, no GitHub token is retained (the access token is used once to read the profile and discarded). Sessions are random 192-bit tokens in an HttpOnly, Secure, SameSite=None cookie on the API domain, valid 30 days. Sign-out deletes the session.
