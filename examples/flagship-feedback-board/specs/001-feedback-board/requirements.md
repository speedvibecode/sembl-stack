# Requirements

- route: GET /api/health
- table: feedback_items
- Authenticated users only read and write feedback rows where user_id equals auth.uid().
- The client must never use service-role secrets.
- Status views should cover open, planned, and closed feedback.
- The migration must enable RLS and grant authenticated Data API access.
