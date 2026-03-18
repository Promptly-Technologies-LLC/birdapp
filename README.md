# Birdapp: a Twitter/X CLI tool

A command-line tool for posting tweets to Twitter/X from the command line.

## Setup

This repo uses the `uv` package manager to manage dependencies. If you don't already have `uv` installed, you can install it with the following curl command:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

To verify install, use:

```bash
uv --version
```

Consult the [uv installation docs](https://astral.sh/uv/) for more detailed instructions and troubleshooting.

## Installation

You can install the CLI tool globally using uv:

```bash
uv tool install -U birdapp
```

After installation, you can use:

```bash
birdapp auth config
birdapp tweet --text "Hello world!"
```

## Configuration

There are two login flows available through birdapp: OAuth1 and OAuth2. Both require [creating an X "app" in the X Developer Dashboard](https://developer.x.com/en/portal/projects-and-apps).

**Important:** The X API no longer has a free tier. All API usage is billed on a usage basis. You will need to enable billing in your X Developer Dashboard and add funds to your account before you can make API calls.

When creating your app, X requires a **Website URL** and a **Callback URI**:
- **Website URL**: You can enter any valid URL here (e.g., `https://example.com`).
- **Callback URI**: Set this to `http://127.0.0.1:8080/callback`. Birdapp starts a local server at this address to capture the OAuth2 callback automatically.

Once you've created your app, click the "Keys and Tokens" button for the app to generate authentication credentials.

With OAuth1, you generate a "Consumer Key" and "Secret Key" along with an "Access Token" and "Access Token Secret" that provide API access to a single X account. Store these in your birdapp config, and they work forever.

With OAuth2, you generate a "Client ID" and "Client Secret" for your X app, store these app secrets in your birdapp config, and login to your X accounts via a two-step flow that involves authorizing the app per-account in your browser.

In general, OAuth1 is simpler for tweeting from a single account, while OAuth2 is better for tweeting from multiple accounts. (With OAuth1 you would need a separate developer account for each account you want to use.)

OAuth2 is also generally more secure, because it doesn't involve storing secrets that could give an attacker permanent and sweeping access to your account.

### Setting Up Credentials

Run the configuration command to set up your credentials: `birdapp auth config`

- Choose OAuth1 or OAuth2 based on your app registration and security posture.
- OAuth1: run `birdapp auth config --oauth1` per profile.
- OAuth2: run `birdapp auth config --oauth2` once, then `birdapp auth login` per account.
  - Optional: `birdapp auth whoami` to verify the token after login.

This will prompt you for your Twitter API credentials and store them securely in
`~/.config/birdapp/config.json`.

To view your current configuration status (without showing secrets):

```bash
birdapp auth config --show
```

### Profiles

Birdapp stores credentials by username profile. Each profile is keyed by the X username
(without `@`).

How profiles are created:
- OAuth1: created when you run `birdapp auth config --oauth1` and enter a username.
- OAuth2: created when you run `birdapp auth login` (the username comes from the login).

How profiles are selected:
- Set the active profile with `birdapp profile use <username>`.
- Use `--profile <username>` to override the active profile for a single command.
- To list available profiles, run `birdapp profile list`.

## Usage

### Posting Tweets

To post a tweet:

```bash
birdapp tweet --text "Your tweet content here"
```

To post a tweet with media:

```bash
birdapp tweet --text "Check out this image!" --media /path/to/image.jpg
```

To post a media-only tweet (no text):

```bash
birdapp tweet --media /path/to/image.jpg
```

### Replying to Tweets

To reply to a tweet using its ID:

```bash
birdapp tweet --text "Great point!" --reply-to 1234567890
```

To reply to a tweet using its URL:

```bash
birdapp tweet --text "I agree!" --reply-to "https://x.com/user/status/1234567890"
```

You can also include media in replies:

```bash
birdapp tweet --text "Here's my response" --media /path/to/image.jpg --reply-to 1234567890
```

### Getting Tweets

To retrieve tweets by ID (up to 100 at a time):

```bash
birdapp get 1234567890
birdapp get 1234567890 9876543210 --format detailed
birdapp get 1234567890 --json
```

### Looking Up Users

To look up users by username or ID (up to 100 at a time):

```bash
birdapp user elonmusk
birdapp user @nasa @spacex
birdapp user 44196397 --by-id
birdapp user elonmusk --format detailed --fields public_metrics created_at
```

### Importing your tweets (recommended: Twitter data export ZIP)

birdapp supports bulk import of your tweets from Twitter/X’s **“Download your data”** export ZIP:

```bash
birdapp import-archive --path /path/to/twitter-archive.zip
```

To get the ZIP from Twitter/X:

- **Request the export**: go to **Settings** → **Your account** → **Download an archive of your data** (wording may vary) and request the archive.
- **Wait for processing**: it can take ~24 hours.
- **Download**: you’ll get an email with a download link once it’s ready.

### Importing from the Twitter Community Archive (optional)

If you have shared your tweets with the public via the Twitter Community Archive, you can download them from the archive and import them into a SQLite database:

```bash
birdapp import-archive --username yourusername
```

If you've already downloaded `archive.json`, you can import it from a local file. The importer auto-detects the file type and safely parses the JSON payloads:

```bash
birdapp import-archive --path /path/to/archive.json
```

### Multi-account support

You can import multiple archives into the same database.

```bash
birdapp import-archive --username alice
birdapp import-archive --username bob
```

### Searching stored tweets (keyword)

Keyword search uses SQLite FTS5 for full-text search across imported tweets:

```bash
birdapp search "machine learning" --limit 20
birdapp search "climate policy" --author @alice
birdapp search "startup" --since 2024-01-01 --until 2024-06-30
birdapp search "distributed systems" --json
```

### Semantic search (embeddings)

Semantic search is opt-in and uses embeddings. It requires `OPENAI_API_KEY` and the `sqlite-vec` extension. You can optionally override the model with `BIRDAPP_EMBEDDING_MODEL`.

To configure these durably:

```bash
birdapp embed config --api-key sk-... --model text-embedding-3-small
birdapp embed config --show
```

Environment variables still take precedence if set.

Generate embeddings for stored tweets:

```bash
birdapp embed
birdapp embed --db sqlite:////path/to/birdapp.db --model text-embedding-3-small
```

Then run semantic search:

```bash
birdapp search "productivity systems" --semantic --limit 10
birdapp search "startup hiring" --semantic --author @alice
```

You can also embed immediately after import:

```bash
birdapp import-archive --username yourusername --embed
```

### Help

To see all available commands:

```bash
birdapp --help
```

To see help for a specific command:

```bash
birdapp tweet --help
birdapp auth --help
birdapp get --help
birdapp user --help
```
## Contributing

Pull requests are welcome! Please open an issue first to discuss any changes you want to make.

To run the tests, first capture test fixtures:

```bash
uv run tests/capture_oauth2_fixtures.py
```

Then run the tests:

```bash
uv run pytest
```

To lint and type check:

```bash
uv run ruff check --fix
uv run ty check
```

Commit messages must follow the [Conventional Commits](https://www.conventionalcommits.org/) specification.
