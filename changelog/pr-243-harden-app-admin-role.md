# Harden application admin privileges

- Limits the application Admin group to non-sensitive billing model permissions.
- Keeps Django privilege fields and superuser accounts exclusive to existing superusers.
- Prevents application admins from editing or resetting a superuser through the built-in user management.
- Adds regression coverage for the affected permission and account-takeover paths.
