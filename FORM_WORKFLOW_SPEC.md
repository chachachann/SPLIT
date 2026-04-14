# Form Workflow Rebuild Specification

Release target: `v0.06.0a`

## Terms

- `Form Template`: the reusable structure, field rules, access settings, review logic, deadlines, and promotion rules.
- `Filed Form`: one submitted instance of a template.
- `Case`: the tracking-number container that groups one or many filed forms.
- `Case Tab`: one filed form displayed inside a case view.
- `Global Form Library`: the shared case list visible to all logged-in users.
- `Quick Access`: the shared dashboard bucket for both fillable templates and open promoted work.

## Role Model

- Only `Developer` and the existing elevated regional-admin role in SPLIT can create or edit form templates.
- No new platform role is introduced for this rebuild.
- `Developer` and the existing elevated regional-admin role can archive whole cases.
- Archived cases are visible only to `Developer` and the existing elevated regional-admin role.

## Product Direction

This module is not a simple form creator. It is a case-based workflow, assignment, and review system.

The current one-submission model must evolve into:

- case-level tracking
- tabbed filed forms inside each case
- one-to-many promotions
- role-pool claiming
- pending assignment approval
- field-level privacy

## Library Model

### Global Form Library

- The library is one shared page for all logged-in users.
- The library lists `Cases`, not individual filed forms.
- Each library row is identified by `tracking number`.
- Each row shows a combined summary status for the whole case.
- The library supports a `template` filter.
- Library row previews must be safe metadata only, not field values.

### Case Detail

- Clicking a tracking number opens one case detail view.
- Filed forms inside the case are rendered as tabs.
- A promoted form appears as a new tab under the same tracking number.
- Tabs the user is not allowed to access are completely hidden.

### Case Visibility

A case appears in the library if the user can access at least one tab in the case, or the user is the requester.

### Archived Visibility

- Archived cases do not appear to normal users.
- Archived cases remain available only to `Developer` and the existing elevated regional-admin role.

## Quick Access Model

Quick Access remains one shared UI bucket and contains two item types:

- published form templates the user can file
- open promoted work tabs available to the user's role pool

Quick Access does not split these into separate modules.

## Access Model

Template access must be split into separate rule sets.

### Submit Access

Controls who can start and file a form template.

### Library Visibility

Controls who can view filed forms from that template in the global library and inside case tabs.

### Assignment Pool Access

Controls which roles or users can see an `Open` promoted tab and take it from the pool.

### Assignment Approval Access

Controls who can approve a `Pending Assignment`.

### Review Access

Controls who can verify, accept, or reject the filed form during review workflow.

## Privacy Model

### Field Privacy

Each field supports:

- `public`
- `private`

Private fields are visible to:

- requester
- `Developer`
- existing elevated regional-admin role
- active accepter / verifier / reviewer
- eligible users viewing an `Open` tab they can take

### Attachment Privacy

Attachments inherit the privacy of the field they belong to.

### Reviewer Rule

Nothing is private to the reviewers while reviewing the document.

### Requester Rule

The requester can see every tab in the case as read-only, including promoted tabs.

## Template Builder Rebuild

The builder must be rebuilt around typed sections instead of JSON-first editing.

Required sections:

- `Basics`
- `Quick Access`
- `Submit Access`
- `Library Visibility`
- `Assignment Pool`
- `Assignment Approval`
- `Fields`
- `Review Workflow`
- `Promotions`
- `Preview`
- `Publish`

### Field Builder

Each field must support:

- label
- key
- type
- help text
- required
- default value
- validation
- conditional logic
- privacy flag
- hide on promotion

## Workflow Model

### Base Rules

- No-review templates complete immediately on submit.
- A template can define default deadline rules.
- A reviewer can override the deadline while approving or promoting.
- Promotions can create one or many next filed forms.
- Promoted filed forms stay under the same case and tracking number.

### Promotion Rules

One filed form may promote into one, two, or more next templates.

Each promotion target may define:

- target template
- default deadline
- open-pool behavior
- direct assignment behavior
- assignment approval requirement

One approval action may create a mixed set of next tabs, for example:

- one `Open` pool tab
- one directly assigned tab
- one tab with pending assignment approval

## Assignment Model

### Open Pool

- Promoted tabs default to `Open` for their allowed role pool unless a direct assignment rule says otherwise.
- Eligible users can see full tab contents before taking the tab.
- Eligible users can click `Take Form`.

### Claiming

- Taking a form locks it immediately.
- If the template has no assignment approver configured, assignment completes immediately.
- If the template has an assignment approver configured, the tab moves to `Pending Assignment`.

### Assignment Approval

`Pending Assignment` can be approved or rejected by:

- existing elevated regional-admin role
- `Developer`
- configured assignment reviewer

If rejected:

- the tab returns to `Open`

### Reassignment

- Assigned tabs can be reopened back to `Open`
- Assigned tabs can be reassigned directly to another user

## Status Model

### Tab Statuses

- `Open`
- `Pending Assignment`
- `Assigned`
- `In Review`
- `Completed`
- `Rejected`
- `Cancelled`

### Case Summary Status

The library row uses a combined summary status with this priority:

1. `In Review`
2. `Pending Assignment`
3. `Assigned`
4. `Open`
5. `Rejected`
6. `Cancelled`
7. `Completed`

## Archive Rules

- Archive happens at the whole-case level only.
- Pending or otherwise active cases cannot be archived.
- Only `Developer` and the existing elevated regional-admin role can archive.

## Required Data Model Direction

The current schema must evolve toward these core entities:

- `workflow_cases`
- `workflow_case_tabs`
- `workflow_template_submit_access`
- `workflow_template_library_visibility`
- `workflow_template_assignment_pools`
- `workflow_template_assignment_reviewers`
- `workflow_template_promotions`
- `workflow_tab_assignments`
- `workflow_tab_assignment_history`
- `workflow_tab_values`
- `workflow_tab_files`

The current `forms` and `form_submissions` tables can be migrated incrementally, but the final target is case-based, not standalone-submission-based.

## Required Routes and Screens

### Dashboard

- add `Form Library` to the main dashboard sidebar for everyone
- keep `Quick Access` for both fillable templates and open promoted work

### Shared Library

- `/forms/manage/library`
- shared case list for all logged-in users
- case rows by tracking number
- filters by template, status, requester, assignee, deadline

### Case Detail

- `/forms/cases/<tracking_number>`
- tabbed filed forms
- hidden-tab enforcement
- read-only and action modes based on access

### Template Builder

- rebuilt admin-only builder
- typed controls for access, privacy, assignment, review, and promotions

## Migration Strategy

### Phase 1

- make the Form Library globally reachable
- filter library rows by actual visibility
- hide archived cases from normal users
- document the new case-based model

### Phase 2

- split template access into submit, library, pool, assignment-approval, and review rules
- add field privacy flags

### Phase 3

- introduce case and tab tables
- move library from submission rows to case rows

### Phase 4

- replace single next-form promotion with one-to-many promotion rules
- add open pool, take form, pending assignment, approve assignment, reject assignment

### Phase 5

- rebuild the template builder UI on top of the new model

## Implementation Note

The rebuild must preserve the important working features already in the codebase:

- published-form quick access
- autosave drafts
- direct-complete no-review forms
- deadlines and late-state labeling
- review queues
- comments
- audit trail
- existing notification behavior

The rebuild should replace the current access model, not layer more special cases onto it.
