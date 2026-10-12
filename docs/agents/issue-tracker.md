# Linear Issue Tracker

Issues for this repository are tracked in Linear using the `orca linear` CLI.

- **Workspace:** LinearFB
- **Team:** LIN (LinearFB)
- **Project:** Arny (ID: `b5c53b8a-dcf1-4c8a-b574-8dbbc02368b4`)
- **URL:** https://linear.app/linearfb/project/arny-6c9309b403d0

## Workflows

All task management, backlog queries, and ticket creation are performed through the Linear CLI.

### Listing Issues
```bash
orca linear list-issues --project b5c53b8a-dcf1-4c8a-b574-8dbbc02368b4 --json
```

### Reading an Issue
```bash
orca linear issue <id> --full --json
```

### Creating an Issue
```bash
orca linear create --team LIN --project b5c53b8a-dcf1-4c8a-b574-8dbbc02368b4 --title "<title>" --body-file - --json
```

### Updating Issue Status
```bash
orca linear status set <id> --to "<state>" --json
```
