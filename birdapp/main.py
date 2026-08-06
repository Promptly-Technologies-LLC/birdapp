import argparse
import json
import os
from datetime import UTC, date, datetime

from .config import (
    clear_profile_override,
    get_active_profile,
    get_credential,
    has_profile,
    list_profiles,
    prompt_for_credentials,
    prompt_for_oauth2_credentials,
    set_active_profile,
    set_embedding_credentials,
    set_profile_override,
    show_config,
    show_embedding_config,
)
from .oauth2 import oauth2_login_flow, oauth2_whoami
from .session import has_oauth2_token
from .storage.embeddings import (
    EmbeddingsUnavailable,
    embed_tweets_in_db,
    semantic_results_payload,
    semantic_search_tweets_in_db,
)
from .storage.importer import import_archive
from .storage.search import search_results_payload, search_tweets_in_db
from .tweet import get_tweets_by_ids, post_tweet
from .user import (
    AVAILABLE_EXPANSIONS,
    AVAILABLE_TWEET_FIELDS,
    AVAILABLE_USER_FIELDS,
    get_user_by_id,
    get_user_by_username,
    get_users_by_ids,
    get_users_by_usernames,
)


def _get_env_or_config(key: str) -> str | None:
    return os.getenv(key) or get_credential(key)


def _has_oauth1_credentials() -> bool:
    return all(
        _get_env_or_config(key)
        for key in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
        )
    )


def _has_oauth2_config() -> bool:
    return bool(
        _get_env_or_config("X_OAUTH2_CLIENT_ID")
        and _get_env_or_config("X_OAUTH2_REDIRECT_URI")
    )


def _prompt_for_auth_flow() -> str:
    print("Select authentication flow:")
    print("  1) OAuth1 (user tokens)")
    print("  2) OAuth2 (authorization code with PKCE)")
    while True:
        choice = input("Choose 1 or 2 (oauth1/oauth2): ").strip().lower()
        if choice in {"1", "oauth1", "oauth 1"}:
            return "oauth1"
        if choice in {"2", "oauth2", "oauth 2"}:
            return "oauth2"
        print("Please enter 1 or 2.")


def _parse_date(value: str | None, *, flag: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid date for {flag}. Use YYYY-MM-DD.") from exc


def _format_search_timestamp(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    return (
        value.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _format_tweet_url(username: str, tweet_id: str) -> str:
    return f"https://x.com/{username}/status/{tweet_id}"


def main() -> None:
    """Main CLI entry point"""
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--profile",
        type=str,
        default=argparse.SUPPRESS,
        help="Use a specific profile for this command",
    )

    parser = argparse.ArgumentParser(
        description="X CLI - Post tweets from the command line",
        parents=[common_parser],
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands", required=True)
    # Profile subcommand
    profile_parser = subparsers.add_parser(
        "profile",
        help="Manage profiles",
        parents=[common_parser],
    )
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_use_parser = profile_subparsers.add_parser(
        "use",
        help="Set active profile",
        parents=[common_parser],
    )
    profile_use_parser.add_argument("username", type=str, help="Profile username to activate")
    profile_subparsers.add_parser(
        "list",
        help="List available profiles",
        parents=[common_parser],
    )
    profile_show_parser = profile_subparsers.add_parser(
        "show",
        help="Show profile configuration",
        parents=[common_parser],
    )
    profile_show_parser.add_argument("username", nargs="?", help="Profile username")


    # Auth subcommand
    auth_parser = subparsers.add_parser(
        "auth",
        help="Authentication and credential management",
        parents=[common_parser],
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)

    auth_config_parser = auth_subparsers.add_parser(
        "config",
        help="Configure authentication",
        parents=[common_parser],
    )
    auth_config_parser.add_argument("--show", action="store_true", help="Show current configuration")
    auth_flow_group = auth_config_parser.add_mutually_exclusive_group()
    auth_flow_group.add_argument("--oauth1", action="store_true", help="Configure OAuth1 credentials")
    auth_flow_group.add_argument("--oauth2", action="store_true", help="Configure OAuth2 credentials")

    auth_login_parser = auth_subparsers.add_parser(
        "login",
        help="Authenticate via OAuth2",
        parents=[common_parser],
    )
    auth_login_parser.add_argument("--json", action="store_true", help="Output raw JSON response")

    auth_whoami_parser = auth_subparsers.add_parser(
        "whoami",
        help="Show authenticated user info",
        parents=[common_parser],
    )
    auth_whoami_parser.add_argument(
        "--user-id", dest="user_id", type=str, help="Use stored token for user id"
    )
    auth_whoami_parser.add_argument("--json", action="store_true", help="Output raw JSON response")

    # Tweet subcommand
    tweet_parser = subparsers.add_parser(
        "tweet",
        help="Post a tweet",
        parents=[common_parser],
    )
    tweet_parser.add_argument(
        "text",
        nargs="?",
        default=None,
        help="Tweet text to post (optional if media provided)",
    )
    tweet_parser.add_argument(
        "--text",
        dest="text_flag",
        type=str,
        default=None,
        help="Tweet text to post (optional if media provided)",
    )
    tweet_parser.add_argument('--media', type=str, help='Path to media file (optional)')
    tweet_parser.add_argument('--reply-to', dest='reply_to', type=str, help='Tweet ID or URL to reply to (optional)')
    
    # Get tweets subcommand
    get_parser = subparsers.add_parser(
        "get",
        help="Get tweets by ID",
        parents=[common_parser],
    )
    get_parser.add_argument('ids', nargs='+', help='Tweet IDs to retrieve (space separated)')
    get_parser.add_argument('--json', action='store_true', help='Output raw JSON response')
    get_parser.add_argument('--format', choices=['simple', 'detailed'], default='simple', 
                           help='Output format (simple or detailed)')
    
    # User lookup subcommand
    user_parser = subparsers.add_parser(
        "user",
        help="Look up user information",
        parents=[common_parser],
    )
    user_parser.add_argument('identifiers', nargs='+', 
                            help='User IDs or usernames to look up (usernames can have @ prefix)')
    user_parser.add_argument('--by-id', action='store_true', 
                            help='Force lookup by ID (default: auto-detect based on format)')
    user_parser.add_argument('--by-username', action='store_true', 
                            help='Force lookup by username (default: auto-detect based on format)')
    user_parser.add_argument('--fields', nargs='+', choices=AVAILABLE_USER_FIELDS,
                            help='User fields to include in response')
    user_parser.add_argument('--expansions', nargs='+', choices=AVAILABLE_EXPANSIONS,
                            help='Data expansions to include')
    user_parser.add_argument('--tweet-fields', nargs='+', choices=AVAILABLE_TWEET_FIELDS,
                            help='Tweet fields to include when expanding tweets')
    user_parser.add_argument('--json', action='store_true', 
                            help='Output raw JSON response')
    user_parser.add_argument('--format', choices=['simple', 'detailed', 'full'], default='simple',
                            help='Output format (simple, detailed, or full)')

    # Import archive subcommand
    import_parser = subparsers.add_parser(
        "import-archive",
        help="Import a Twitter Community Archive into a SQLite database",
        parents=[common_parser],
    )
    import_parser.add_argument('--username', type=str, help='Archive username')
    import_parser.add_argument('--url', type=str, help='Full archive.json URL')
    import_parser.add_argument('--path', type=str, help='Path to a local archive.json file')
    import_parser.add_argument(
        '--db',
        type=str,
        default=None,
        help='Database URL (default: ~/.local/share/birdapp/birdapp.db)',
    )
    import_parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for inserts (default: 1000)',
    )
    import_parser.add_argument('--json', action='store_true', help='Output raw JSON result')
    import_parser.add_argument(
        "--embed",
        action="store_true",
        help="Generate embeddings after import",
    )

    # Search stored tweets subcommand
    search_parser = subparsers.add_parser(
        "search",
        help="Search stored tweets in the local SQLite database",
    )
    search_parser.add_argument("query", type=str, help="FTS query string")
    search_parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Database URL (default: ~/.local/share/birdapp/birdapp.db)",
    )
    search_parser.add_argument("--author", type=str, help="Filter by owner username")
    search_parser.add_argument("--since", type=str, help="Filter by date (YYYY-MM-DD)")
    search_parser.add_argument("--until", type=str, help="Filter by date (YYYY-MM-DD)")
    search_parser.add_argument("--limit", type=int, default=20, help="Max results")
    search_parser.add_argument("--json", action="store_true", help="Output raw JSON result")
    search_parser.add_argument(
        "--include-url",
        action="store_true",
        help="Include tweet URLs in the output",
    )
    search_parser.add_argument(
        "--semantic",
        action="store_true",
        help="Use semantic search with embeddings",
    )

    # Embed stored tweets subcommand
    embed_parser = subparsers.add_parser(
        "embed",
        help="Generate embeddings for stored tweets",
        parents=[common_parser],
    )
    embed_subparsers = embed_parser.add_subparsers(dest="embed_command")
    embed_subparsers.required = False
    embed_config_parser = embed_subparsers.add_parser(
        "config",
        help="Configure embedding credentials",
        parents=[common_parser],
    )
    embed_config_parser.add_argument(
        "--api-key",
        type=str,
        help="OpenAI API key",
    )
    embed_config_parser.add_argument(
        "--model",
        type=str,
        help="Embedding model",
    )
    embed_config_parser.add_argument(
        "--show",
        action="store_true",
        help="Show embedding configuration",
    )
    embed_parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Database URL (default: ~/.local/share/birdapp/birdapp.db)",
    )
    embed_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Embedding model override",
    )
    embed_parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for embedding requests (default: 100)",
    )
    
    # Parse arguments
    args = parser.parse_args()
    profile: str | None = getattr(args, "profile", None)
    if profile:
        set_profile_override(profile)
    else:
        clear_profile_override()
    
    # Handle profile command
    if args.command == "profile":
        if args.profile_command == "use":
            if not has_profile(args.username):
                print(f"Profile '{args.username}' not found. Run `birdapp auth config` to create it.")
                return
            set_active_profile(args.username)
            print(f"Active profile set to {args.username}")
            return
        if args.profile_command == "list":
            profiles = list_profiles()
            if not profiles:
                print("No profiles found. Run `birdapp auth config` to create one.")
                return
            active = get_active_profile()
            for profile in profiles:
                marker = "*" if active == profile else " "
                print(f"{marker} {profile}")
            return
        if args.profile_command == "show":
            show_config(profile=args.username)
            return

    # Handle auth command
    if args.command == "auth":
        if args.auth_command == "config":
            if args.show:
                show_config(profile=profile)
            elif args.oauth1:
                prompt_for_credentials(profile=profile)
            elif args.oauth2:
                prompt_for_oauth2_credentials(profile=profile)
            else:
                flow = _prompt_for_auth_flow()
                if flow == "oauth1":
                    prompt_for_credentials(profile=profile)
                else:
                    prompt_for_oauth2_credentials(profile=profile)
        elif args.auth_command == "login":
            if not _has_oauth2_config():
                if _has_oauth1_credentials():
                    print("OAuth1 credentials are configured; no login step is required.")
                else:
                    print("OAuth2 credentials are not configured. Run `birdapp auth config`.")
                return

            try:
                result = oauth2_login_flow(profile=profile)
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(json.dumps(result, indent=2))
            except Exception as e:
                print(f"❌ Error during OAuth2 flow: {e!s}")
        else:
            try:
                result = oauth2_whoami(args.user_id, profile=profile)
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(json.dumps(result, indent=2))
            except Exception as e:
                print(f"❌ Error during OAuth2 flow: {e!s}")
        return
    
    # Handle tweet command
    if args.command == 'tweet':
        if args.text_flag is not None and args.text is not None:
            print("Error: Provide tweet text either positionally or with --text, not both")
            raise SystemExit(1)

        text = (args.text_flag or args.text or "").strip()

        # Validate arguments
        if not text and not args.media:
            print("Error: Cannot post empty tweet without media")
            raise SystemExit(1)

        if _has_oauth2_config() and not has_oauth2_token(profile=profile) and not _has_oauth1_credentials():
            profile_hint = f"--profile {profile} " if profile else ""
            print(
                "No OAuth2 login token is stored for this profile. "
                f"Run `birdapp {profile_hint}auth login` to complete OAuth2 login."
            )
            return
        
        # Post the tweet
        try:
            success, message = post_tweet(
                text=text,
                media_path=args.media,
                reply_to=args.reply_to
            )
            
            if success:
                print(f"✅ Successfully posted tweet: {message}")
            else:
                print(f"❌ Failed to post tweet: {message}")
                
        except Exception as e:
            print(f"❌ Error posting tweet: {e!s}")
    
    # Handle get command
    if args.command == 'get':
        try:
            success, result = get_tweets_by_ids(args.ids)
            
            if success:
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    if isinstance(result, dict):
                        format_tweets_output(result, args.format)
                    else:
                        print(f"❌ Failed to get tweets: {result}")
            else:
                print(f"❌ Failed to get tweets: {result}")
                
        except Exception as e:
            print(f"❌ Error getting tweets: {e!s}")
    
    # Handle user command
    if args.command == 'user':
        try:
            # Determine if we're looking up by ID or username
            identifiers = args.identifiers
            
            # Auto-detect type if not forced
            if not args.by_id and not args.by_username:
                # Check if all identifiers look like IDs (all digits) or usernames
                all_digits = all(ident.isdigit() for ident in identifiers)
                if all_digits:
                    by_id = True
                else:
                    by_id = False
            else:
                by_id = args.by_id
            
            # Perform the lookup
            if len(identifiers) == 1:
                # Single user lookup
                if by_id:
                    success, result = get_user_by_id(
                        identifiers[0],
                        user_fields=args.fields,
                        expansions=args.expansions,
                        tweet_fields=args.tweet_fields
                    )
                else:
                    success, result = get_user_by_username(
                        identifiers[0],
                        user_fields=args.fields,
                        expansions=args.expansions,
                        tweet_fields=args.tweet_fields
                    )
            else:
                # Multiple users lookup
                if by_id:
                    success, result = get_users_by_ids(
                        identifiers,
                        user_fields=args.fields,
                        expansions=args.expansions,
                        tweet_fields=args.tweet_fields
                    )
                else:
                    success, result = get_users_by_usernames(
                        identifiers,
                        user_fields=args.fields,
                        expansions=args.expansions,
                        tweet_fields=args.tweet_fields
                    )
            
            if success:
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    if isinstance(result, dict):
                        format_users_output(result, args.format)
                    else:
                        print(f"❌ Failed to get user(s): {result}")
            else:
                print(f"❌ Failed to get user(s): {result}")
                
        except Exception as e:
            print(f"❌ Error getting user(s): {e!s}")

    # Handle import-archive command
    if args.command == 'import-archive':
        try:
            username = args.username
            if not username and not args.url and not args.path:
                username = get_credential("X_USERNAME")
            result = import_archive(
                args.db,
                username=username,
                url=args.url,
                path=args.path,
                batch_size=args.batch_size,
            )
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                total = sum(result.values())
                print(f"✅ Imported {total} rows")
                for key, value in result.items():
                    print(f"{key}: {value}")
            if args.embed:
                embedded = embed_tweets_in_db(
                    args.db,
                    model_override=None,
                    batch_size=args.batch_size,
                )
                print(f"✅ Embedded {embedded} tweets")
        except Exception as e:
            print(f"❌ Error importing archive: {e!s}")
        return

    # Handle search command
    if args.command == "search":
        try:
            since = _parse_date(args.since, flag="--since")
            until = _parse_date(args.until, flag="--until")
            if args.semantic:
                results = semantic_search_tweets_in_db(
                    args.db,
                    query=args.query,
                    author=args.author,
                    since=since,
                    until=until,
                    limit=args.limit,
                    model_override=None,
                )
                if args.json:
                    print(json.dumps(semantic_results_payload(results), indent=2))
                else:
                    if not results:
                        print("No results found.")
                        return
                    for result in results:
                        created_at = _format_search_timestamp(result.created_at)
                        print(f"Tweet ID: {result.tweet_id}")
                        print(
                            "Owner: "
                            f"@{result.owner_username} "
                            f"({result.owner_display_name})"
                        )
                        print(f"Created: {created_at}")
                        if args.include_url:
                            url = _format_tweet_url(result.owner_username, result.tweet_id)
                            print(f"URL: {url}")
                        print(f"Text: {result.full_text}")
                        print("-" * 50)
            else:
                results = search_tweets_in_db(
                    args.db,
                    query=args.query,
                    author=args.author,
                    since=since,
                    until=until,
                    limit=args.limit,
                )
                if args.json:
                    print(json.dumps(search_results_payload(results), indent=2))
                else:
                    if not results:
                        print("No results found.")
                        return
                    for result in results:
                        created_at = _format_search_timestamp(result.created_at)
                        print(f"Tweet ID: {result.tweet_id}")
                        print(
                            "Owner: "
                            f"@{result.owner.username} "
                            f"({result.owner.account_display_name})"
                        )
                        print(f"Created: {created_at}")
                        if args.include_url:
                            url = _format_tweet_url(result.owner.username, result.tweet_id)
                            print(f"URL: {url}")
                        print(f"Text: {result.full_text}")
                        print("-" * 50)
        except Exception as e:
            if isinstance(e, EmbeddingsUnavailable):
                print(str(e))
            else:
                print(f"❌ Error searching tweets: {e!s}")
        return

    # Handle embed command
    if args.command == "embed":
        if args.embed_command == "config":
            if args.show:
                show_embedding_config()
                return
            if not args.api_key:
                print("OPENAI_API_KEY is required.")
                return
            set_embedding_credentials(api_key=args.api_key, model=args.model)
            print("✅ Embedding configuration saved.")
            return
        try:
            embedded = embed_tweets_in_db(
                args.db,
                model_override=args.model,
                batch_size=args.batch_size,
            )
            print(f"✅ Embedded {embedded} tweets")
        except Exception as e:
            print(f"❌ Error generating embeddings: {e!s}")
        return

def format_tweets_output(data: dict, format_type: str):
    """Format and display tweet data"""
    if 'data' not in data:
        print("No tweets found")
        return
    
    tweets = data['data']
    users = {user['id']: user for user in data.get('includes', {}).get('users', [])}
    
    for tweet in tweets:
        author_id = tweet.get('author_id')
        author = users.get(author_id, {})
        
        if format_type == 'simple':
            print(f"Tweet ID: {tweet['id']}")
            print(f"Author: @{author.get('username', 'unknown')} ({author.get('name', 'Unknown')})")
            print(f"Text: {tweet['text']}")
            print(f"Created: {tweet.get('created_at', 'unknown')}")
            print("-" * 50)
        else:  # detailed
            print(f"Tweet ID: {tweet['id']}")
            print(f"Author: @{author.get('username', 'unknown')} ({author.get('name', 'Unknown')})")
            print(f"Text: {tweet['text']}")
            print(f"Created: {tweet.get('created_at', 'unknown')}")
            print(f"Language: {tweet.get('lang', 'unknown')}")
            
            if 'public_metrics' in tweet:
                metrics = tweet['public_metrics']
                print(f"Likes: {metrics.get('like_count', 0)}")
                print(f"Retweets: {metrics.get('retweet_count', 0)}")
                print(f"Replies: {metrics.get('reply_count', 0)}")
                print(f"Quotes: {metrics.get('quote_count', 0)}")
            
            if author.get('verified'):
                print("✓ Verified account")
            
            print("-" * 50)

def format_users_output(data: dict, format_type: str):
    """Format and display user data"""
    if 'data' not in data:
        print("No users found")
        return
    
    # Handle both single user and multiple users response
    users = data['data']
    if isinstance(users, dict):
        users = [users]  # Convert single user to list for uniform handling
    
    # Get expanded tweet data if available
    tweets = {}
    if 'includes' in data and 'tweets' in data['includes']:
        for tweet in data['includes']['tweets']:
            tweets[tweet['id']] = tweet
    
    for user in users:
        if format_type == 'simple':
            print(f"User ID: {user['id']}")
            print(f"Username: @{user['username']}")
            print(f"Name: {user['name']}")
            if 'description' in user:
                print(f"Bio: {user.get('description', '')[:100]}...")
            print("-" * 50)
            
        elif format_type == 'detailed':
            print(f"User ID: {user['id']}")
            print(f"Username: @{user['username']}")
            print(f"Name: {user['name']}")
            
            if 'description' in user:
                print(f"Bio: {user['description']}")
            
            if 'created_at' in user:
                print(f"Joined: {user['created_at']}")
            
            if 'location' in user:
                print(f"Location: {user['location']}")
            
            if 'url' in user:
                print(f"Website: {user['url']}")
            
            if 'public_metrics' in user:
                metrics = user['public_metrics']
                print(f"Followers: {metrics.get('followers_count', 0):,}")
                print(f"Following: {metrics.get('following_count', 0):,}")
                print(f"Tweets: {metrics.get('tweet_count', 0):,}")
                print(f"Listed: {metrics.get('listed_count', 0):,}")
            
            if user.get('verified'):
                print("✓ Verified account")
            
            if user.get('protected'):
                print("🔒 Protected account")
            
            print("-" * 50)
            
        else:  # full
            print("=== User Profile ===")
            print(f"User ID: {user['id']}")
            print(f"Username: @{user['username']}")
            print(f"Name: {user['name']}")
            
            if 'description' in user:
                print(f"\nBio: {user['description']}")
            
            if 'created_at' in user:
                print(f"\nAccount created: {user['created_at']}")
            
            if 'location' in user:
                print(f"Location: {user['location']}")
            
            if 'url' in user:
                print(f"Website: {user['url']}")
            
            if 'profile_image_url' in user:
                print(f"Profile image: {user['profile_image_url']}")
            
            if 'profile_banner_url' in user:
                print(f"Banner image: {user['profile_banner_url']}")
            
            if 'public_metrics' in user:
                print("\n=== Metrics ===")
                metrics = user['public_metrics']
                print(f"Followers: {metrics.get('followers_count', 0):,}")
                print(f"Following: {metrics.get('following_count', 0):,}")
                print(f"Tweets: {metrics.get('tweet_count', 0):,}")
                print(f"Listed: {metrics.get('listed_count', 0):,}")
            
            # Account status
            status_items = []
            if user.get('verified'):
                status_items.append("✓ Verified")
            if user.get('protected'):
                status_items.append("🔒 Protected")
            if user.get('is_identity_verified'):
                status_items.append("🆔 Identity Verified")
            
            if status_items:
                print("\n=== Account Status ===")
                print(" | ".join(status_items))
            
            # Show pinned tweet if expanded
            if 'pinned_tweet_id' in user and user['pinned_tweet_id'] in tweets:
                pinned = tweets[user['pinned_tweet_id']]
                print("\n=== Pinned Tweet ===")
                print(f"ID: {pinned['id']}")
                print(f"Text: {pinned['text']}")
                if 'created_at' in pinned:
                    print(f"Posted: {pinned['created_at']}")
            
            # Show most recent tweet if expanded
            if 'most_recent_tweet_id' in user and user['most_recent_tweet_id'] in tweets:
                recent = tweets[user['most_recent_tweet_id']]
                print("\n=== Most Recent Tweet ===")
                print(f"ID: {recent['id']}")
                print(f"Text: {recent['text']}")
                if 'created_at' in recent:
                    print(f"Posted: {recent['created_at']}")
            
            print("=" * 50)

if __name__ == "__main__":
    main()