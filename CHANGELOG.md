# CHANGELOG

<!-- version list -->

## v2.1.4 (2026-03-18)

### Bug Fixes

- Update credential names to match X dashboard and clear stale OAuth2 tokens
  ([`4387d35`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/4387d3589110769cc50e2816264d5c51918d785c))


## v2.1.3 (2026-03-13)

### Bug Fixes

- Error message for OAuth2 no longer references OAuth1
  ([`07ea49e`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/07ea49e90178fc7b5300a63a4e8d42fc1590c3b4))

### Build System

- Regenerate uv.lock during release version bump
  ([`a954c93`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/a954c93b3aea63c3eb738f5e96384531c2a04800))

### Documentation

- Update README install command
  ([`fa5439e`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/fa5439e821308081e401db7d5724b7f0d0be05e4))


## v2.1.2 (2026-03-13)

### Bug Fixes

- Add actionable error message for 503 API responses
  ([`86f4afd`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/86f4afd1dbdde772870eea0942898c9d90c96682))


## v2.1.1 (2026-02-03)

### Bug Fixes

- Ensure console output for an expired OAuth2 token never falls back to OAuth1 instructions
  ([`a23449d`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/a23449d12bdb8fe4ff36f293e26a1fd430e4249e))


## v2.1.0 (2026-01-28)

### Bug Fixes

- Shared date formatter for search results
  ([`1c15261`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/1c15261949482bf4617d2aa4c70785c2c5db0afd))

### Features

- Optionally include tweet URL in search results
  ([`9fb33e7`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/9fb33e7e94663ef8c3de42c16f6045285249d76e))


## v2.0.0 (2026-01-27)

### Bug Fixes

- Use a new canonical location for session storage
  ([`fd22aef`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/fd22aef68c6a9356c2b223d7f2ffd8cffff1a06d))


## v1.4.3 (2026-01-25)

### Bug Fixes

- Increase accuracy of 'auth config --show' output
  ([`36ecffe`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/36ecffe212e9a1db9cb754e68b0d8cc2824c43bb))


## v1.4.2 (2026-01-25)

### Bug Fixes

- Auto-refresh expired OAuth2 tokens and add tweet.write as default scope
  ([`cd720bf`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/cd720bf66decc3f2c2daf43ca429870f789f898e))

### Documentation

- Make sure profile flag shows up in help
  ([`063b822`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/063b822d35df0c976fa6783a9f336d0686b039c2))


## v1.4.1 (2026-01-25)

### Bug Fixes

- Search returns valid dates
  ([`43b78f2`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/43b78f2527fb8bd66c4fec0b0119f477cbd91e23))


## v1.4.0 (2026-01-24)

### Documentation

- Document zip import
  ([`2812861`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/28128619fc4d0628aca089fd4c0a56e74164e318))

### Features

- Support ingesting downloaded X archive zip
  ([`c93e057`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/c93e05730310ce5c55be042dd98ba6263fc33e3b))


## v1.3.0 (2026-01-24)

### Features

- Allow tweeting with a positional text argument
  ([`722870c`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/722870c8fd45f6935fc1b322262c89546f688ef2))


## v1.2.0 (2026-01-23)

### Bug Fixes

- Mock credential in failing test
  ([`2642113`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/2642113f1164fe813002ce1b8f4c446e6730e6d1))

### Documentation

- Brainstorming Cursor rule
  ([`47610d5`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/47610d56aeb6e4d7f7e1911164f229ba426dc1d1))

- Clarify auth flows
  ([`a5e2ae5`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/a5e2ae50e6b22d4be91a22d30dc4178e6eae27f1))

- Storage module documentation
  ([`d14e209`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/d14e2093b1d5fbef0c03670e340a1886908599d6))

### Features

- Durably config model and API key
  ([`a5add49`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/a5add495e017831b6045a78757380243d4e9a72d))

- Feature 3: Embeddings & Semantic Search
  ([`f9b8bd7`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/f9b8bd78766841fb9642e3bc28f5a5ed73c41d2a))

- Keyword Search (Stored Tweets)
  ([`7e4e8e2`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/7e4e8e218a04446bb3e82e8963dd4bf7697f0179))

- Multi-User Schema Improvements
  ([`a4416e6`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/a4416e6bac2238b3f6f21d182120c786bcd3449d))

### Testing

- Increase test coverage for search features
  ([`e2aa43f`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/e2aa43fdf5874ea7f3d96fb8cd50a2ee656e9f6c))


## v1.1.0 (2026-01-22)

### Features

- Multi-user auth flow
  ([`3231f12`](https://github.com/Promptly-Technologies-LLC/birdapp/commit/3231f12ac450449e583cf064f20e3b06cbf79cf8))


## v1.0.0 (2026-01-22)

- Initial Release
