# Security policy

Urbanium treats external data, URLs, configuration and serialized payloads as untrusted input.

Security-sensitive changes should consider SSRF, injection, path traversal, unsafe deserialization, secret exposure, dependency vulnerabilities, authentication/authorization boundaries and denial-of-service risks from unbounded urban datasets.

Do not commit credentials, tokens or private infrastructure details. Use environment variables or deployment-specific secret management for secrets.

Please do not publish exploitable vulnerability details in a public issue. Prefer GitHub's private vulnerability reporting / Security Advisory flow when available for this repository. If that channel is unavailable, contact the repository owner privately through GitHub before disclosing technical details.
