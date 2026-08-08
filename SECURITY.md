# Security

Krabville has a deliberately narrow public surface. Report vulnerabilities
privately through GitHub Security Advisories. Do not open an issue containing
credentials, private infrastructure details, personal data, or working exploit
payloads.

The public API is read-only except for fixed-choice poll votes. It accepts no
free text, prompts, commands, paths, model settings, or file uploads. The model
worker runs separately with a read-only sandbox and schema-bound output. Public
fiction is rejected if it contains URLs, addresses, paths, filenames, long
identifiers, secret-related terms, or command text.

Supported releases receive security fixes on the latest `main` release line.
