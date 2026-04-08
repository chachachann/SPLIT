# Form Workflow Specification

## Purpose

This document defines a build-ready product specification for a dynamic form workflow system in SPLIT.

The requested feature is not a simple "form creator." It is a controlled workflow engine with:

- dynamic form templates
- role-based and user-restricted access
- quick access button publishing
- draft and autosave behavior
- conditional fields
- file and image submissions
- multi-stage review routing
- automatic chained next forms
- global tracking numbers with form prefixes
- audit trail, history, and exports
- in-app notifications now and SMTP-ready email later

## Product Positioning

This feature should be treated as a first-class module in the existing platform.

- `Developer` and `SuperAdmin` can access `Config`.
- `Form Manager` and `SMTP Settings` belong under `Config`.
- `Review Queue` and `My Requests` belong in the topbar beside chat and notifications.
- Published forms appear in dashboard `Quick Actions` as cards.

## Recommended Architecture Decision

Do not force this feature into the current legacy `buttons` table directly.

The current `buttons` table only supports:

- name
- route
- one required role

That model is too limited for:

- role AND specific-user access
- per-form icon and card styling
- form status and publish control
- chained workflow rules
- reviewer assignment
- field versioning

Recommended approach:

- Keep the current `buttons` table for legacy/static modules.
- Introduce dedicated form workflow tables.
- Treat a published form as a form-defined quick action card, not as a legacy static button row.

## Core Terms

- `Form Template`: the reusable configuration created in `Form Manager`
- `Form Version`: immutable field structure snapshot used for future submissions
- `Submission`: one user request against one published form version
- `Review Stage`: one level in the approval chain
- `Reviewer Assignment`: a user or role queue responsible for a stage
- `Promotion`: automatic creation of the next form after a qualifying workflow event
- `Tracking Number`: global sequence prefixed by form-defined code

## Permissions

### Platform-level permissions

- `Developer` and `SuperAdmin` can create, edit, publish, archive, restore, and delete form templates.
- `Developer` and `SuperAdmin` can manage any form template.
- Form template editing is limited to `Developer` and `SuperAdmin`.
- Review authority is not implied by `Developer` or `SuperAdmin`.
- A user may view a submission without being allowed to approve it.

### Submission visibility

A submission is visible to:

- the submitter
- assigned reviewers
- the form creator
- `Developer`
- `SuperAdmin`

View access does not equal review authority.

### Form access

Published form access supports:

- role access
- optional specific-user restriction

When both are configured, access is:

- `role AND specific user`

If the user has no access, the form card is hidden.

### Review permissions

Review access supports:

- role-based reviewer assignment
- specific-user reviewer assignment
- both together

Review stages may be:

- sequential
- parallel
- mixed

## Form Template Rules

Each form template supports:

- title
- internal key / slug
- description
- quick action label
- quick action icon
- custom card style/color
- form prefix for tracking numbers
- form status
- publish behavior
- cancellation policy
- multiple active submissions policy
- access roles
- access-specific users
- review workflow definition
- next-form promotion rules
- inheritance visibility rules

### Form statuses

- `draft`
- `published`
- `archived`

Behavior:

- `draft`: not visible in Quick Actions
- `published`: visible to allowed users in Quick Actions
- `archived`: hidden from Quick Actions but retained in Config

Published edits go live immediately for future submissions.
Old submissions remain bound to their original version snapshot.

## Field Builder

### Supported field types in scope

- short text
- long text
- number
- date
- dropdown
- checkbox
- image upload
- file upload

### Field configuration

Each field supports:

- label
- internal field key
- help text
- required flag
- sort order
- default value
- validation rules
- conditional visibility rules
- inheritance visibility rules for promoted stages

### Required fields

"Important" means:

- required to submit
- visually marked with an asterisk

### Validation

Validation is configurable per field and may include:

- min length
- max length
- numeric range
- date rules
- allowed values
- allowed file types

### Conditional logic

Conditional field logic is required in v1.

Supported logic model:

- `AND`
- `OR`
- nested rule groups
- operators:
  - equals
  - not equals
  - contains
  - greater than
  - less than
  - is empty

Conditional logic only uses normal field values, not uploaded files.

## File Upload Rules

### Images

- up to 5 images per submission
- up to 50 MB per file

### Documents

- up to 20 attachments per submission
- up to 50 MB per file

### Allowed file types

Allowed types are fixed globally, not form-specific.

Current requested set:

- SVG
- PNG
- JPEG / JPG
- other supported photo formats
- PDF
- DOC
- DOCX
- XLS
- XLSX
- TXT

Recommended implementation note:

- normalize and validate against an explicit allowed extension set
- do not allow unrestricted "other photo formats" without a defined list

## Submission Lifecycle

### Submission statuses

- `draft`
- `pending`
- `accepted`
- `rejected`
- `cancelled`
- `promoted`
- `completed`
- `archived`

### Status meaning

- `draft`: not yet formally submitted
- `pending`: submitted and waiting for review
- `accepted`: approved at a stage or approved without immediate promotion
- `rejected`: rejected by any active reviewer
- `cancelled`: cancelled by submitter before review action
- `promoted`: forwarded automatically to a next form without needing acceptance
- `completed`: final successful state when no next form remains
- `archived`: hidden from active queues but still retained and searchable

### Submission rules

- Drafts support manual save and autosave.
- Tracking numbers are generated only on formal submit, not on draft create.
- Tracking numbers remain the same even if the submission is cancelled and resubmitted.
- Users may delete their own drafts.
- Drafts do not expire.
- Reviewers cannot edit submitted field values.

### Multiple submissions

One user may submit multiple active submissions for the same form if the form allows it.

There is no global hard limit per user per form.

## Cancellation Rules

- Only allowed before any reviewer acts.
- Submitter must provide a mandatory cancellation reason.
- A form creator can disable cancellation for a specific form template.
- Cancelled submissions remain visible and auditable.
- Cancelled submissions may later be archived by admins.

## Review Workflow Model

### Stage model

A form can define multiple review stages.

Each stage contains:

- stage order
- stage type: sequential or parallel
- reviewers by role
- reviewers by specific user
- stage rule metadata

### Sequential stages

- Later reviewers may see the submission before their turn.
- Later reviewers are fully read-only until activated.
- They cannot approve, reject, or comment before active turn.

### Parallel stages

- All assigned reviewers in the active parallel stage must approve for the stage to pass.
- A rejection by any active reviewer immediately rejects the whole submission.

### Rejection behavior

- Rejection ends the current submission path.
- Rejection reason is mandatory.
- Resubmission reopens with the same tracking number rather than generating a new one.

### Reviewer comments

- One shared comment thread per submission
- each comment shows author identity and timestamp
- comments are visible to any actor who can view the submission

Acceptance note:

- optional

## Promotion and Chained Forms

### Promotion rules

A form may define one or more next-form routes.

Promotion may be triggered by:

- declared rule
- reviewer decision
- field-value rule
- status event

Conflict priority:

- declared rules always win

### Promotion behavior

- Next forms are created automatically.
- Promotion can target:
  - specific user
  - role queue
  - both
- If the submission is forwarded without requiring acceptance first, the current submission becomes `promoted`.
- If a final stage succeeds and no next form exists, the submission becomes `completed`.

### Inherited data

Promoted forms inherit previous-stage data as:

- read-only snapshot

Rules:

- later edits to old stages do not mutate inherited values
- previous-stage data can be expanded via a toggle in the UI
- some inherited fields may be hidden after promotion
- admins can still see hidden-after-promotion fields in audit and export views

## Visibility Model for Promoted Forms

Next-form access can be controlled through:

- role-based access
- specific-user restriction

This allows:

- chain forms available to anyone with the target button role
- chain forms limited further to named users

## Audit Trail

Maximum audit trail is required.

Audit events should include at minimum:

- form created
- form edited
- form published
- form archived
- form restored
- form deleted
- form version created
- field added
- field edited
- field removed
- submission draft saved
- submission submitted
- submission cancelled
- submission resubmitted
- reviewer stage activated
- reviewer approved
- reviewer rejected
- comment added
- next form promoted
- assignment created
- assignment changed
- submission archived
- submission restored
- export generated

Each audit entry should capture:

- event type
- actor username
- actor full name snapshot
- target entity type
- target entity id
- tracking number if applicable
- JSON change payload
- timestamp

## Notifications

### v1

- in-app notifications required
- SMTP configuration present but email sending can be enabled later

### later email behavior

Email should support notifying concerned users for:

- submission created
- review assigned
- accepted
- rejected
- cancelled
- promoted
- completed

## Export Requirements

Export is required in v1 for users who can view the form.

Required export types:

- CSV submissions
- PDF submission summary
- CSV audit logs

## UI Placement

### Config

Visible only to `Developer` and `SuperAdmin`.

Config sections for this feature:

- `Form Manager`
- `SMTP Settings`

### Topbar

Global user surfaces:

- `Review Queue`
- `My Requests`

These should live beside the chat and notification controls, not inside Config.

### Dashboard Quick Actions

Every published form appears as a Quick Action card for allowed users.

Quick Action cards support:

- preset or uploaded icon
- custom label
- custom card color/style

## Recommended Data Model

The following tables are recommended.

### Form templates

`forms`

- id
- form_key
- title
- description
- quick_label
- quick_icon_type
- quick_icon_value
- quick_card_style_json
- tracking_prefix
- status
- allow_cancel
- allow_multiple_active
- created_by_username
- updated_by_username
- created_at
- updated_at
- archived_at

### Form versioning

`form_versions`

- id
- form_id
- version_number
- schema_json
- is_active
- created_by_username
- created_at

### Form fields

`form_fields`

- id
- form_version_id
- field_key
- label
- field_type
- help_text
- is_required
- sort_order
- default_value_json
- validation_json
- conditional_logic_json
- inherit_visibility_mode
- created_at

### Access control

`form_access_roles`

- id
- form_id
- role_name

`form_access_users`

- id
- form_id
- username

### Reviewer definition

`form_review_stages`

- id
- form_id
- stage_number
- stage_name
- stage_mode
- can_view_early
- created_at

`form_review_stage_roles`

- id
- stage_id
- role_name
- sort_order

`form_review_stage_users`

- id
- stage_id
- username
- sort_order

### Promotion rules

`form_promotions`

- id
- form_id
- rule_name
- priority_order
- trigger_type
- condition_json
- next_form_id
- assignment_mode
- target_role_name
- target_username
- inherit_visibility_json
- created_at

### Submission header

`form_submissions`

- id
- tracking_number
- tracking_prefix
- form_id
- form_version_id
- submitter_username
- current_status
- current_stage_number
- parent_submission_id
- root_submission_id
- cancel_reason
- reject_reason
- acceptance_note
- submitted_at
- completed_at
- archived_at
- created_at
- updated_at

### Submission data

`form_submission_values`

- id
- submission_id
- field_key
- value_json
- created_at

### Submission files

`form_submission_files`

- id
- submission_id
- field_key
- original_name
- stored_name
- file_ext
- mime_type
- file_size_bytes
- file_kind
- uploaded_by_username
- created_at

### Reviewer tasks

`form_review_tasks`

- id
- submission_id
- stage_id
- assigned_role_name
- assigned_username
- task_order
- is_active
- task_status
- acted_at
- acted_by_username
- action_note
- created_at

### Shared comments

`form_submission_comments`

- id
- submission_id
- author_username
- author_fullname_snapshot
- body
- created_at

### In-app notifications

`form_notifications`

- id
- username
- event_type
- title
- message
- link_url
- is_read
- created_at

### Audit log

`form_audit_log`

- id
- event_type
- actor_username
- actor_fullname_snapshot
- entity_type
- entity_id
- tracking_number
- payload_json
- created_at

### SMTP config

`smtp_settings`

- id
- host
- port
- username
- password_encrypted
- from_email
- from_name
- use_tls
- updated_by_username
- updated_at

## Recommended Routes / Screens

### Config area

`/settings`

- add `Form Manager`
- add `SMTP Settings`

### Form management

`/forms/manage`

- form list
- filters by status
- create form
- edit form
- publish / archive / restore
- version history

### Form builder

`/forms/manage/<form_key>/builder`

- metadata editor
- field builder
- conditional logic builder
- access settings
- review stage settings
- promotion settings

### User submission view

`/forms/my-requests`

- list own submissions
- status filters
- search by tracking number
- view timeline
- view comments
- cancel eligible submissions
- delete drafts

### Review queue

`/forms/review-queue`

- items awaiting action
- filters by form, status, date, assigned reviewer
- read-only access to future stages
- action controls only for active tasks

### Submission detail

`/forms/submissions/<tracking_number>`

- summary header
- current status
- stage progress
- comment thread
- field values
- inherited prior-stage data
- attachments
- audit timeline

## State Machine Summary

### Draft path

`draft -> pending`

### Review outcomes

`pending -> rejected`

`pending -> accepted`

`pending -> promoted`

`accepted -> completed`

`accepted -> promoted`

### User action

`pending -> cancelled`

### Admin lifecycle

`rejected -> archived`

`cancelled -> archived`

`completed -> archived`

## MVP Recommendation

Build in phases even if the full design is already defined.

### Phase 1

- form templates
- form versions
- field builder
- role access
- specific-user restriction
- quick access publishing
- draft/autosave
- file upload rules
- tracking numbers
- my requests
- review queue
- sequential review
- basic parallel review
- in-app notifications
- audit log

### Phase 2

- nested conditional logic builder UI polish
- automatic promotions to next forms
- inherited read-only snapshots
- hidden-after-promotion field rules
- export suite
- SMTP settings persistence

### Phase 3

- email delivery
- advanced reporting
- admin analytics
- performance tuning for large submission volumes

## Risks and Complexity

Highest complexity areas:

- grouped conditional logic builder
- mixed sequential + parallel review engine
- automatic promotion with assignment routing
- keeping old submission structure immutable while forms evolve
- full audit coverage without missing edge cases

The feature is achievable, but only if schema versioning and workflow state rules are designed first and implemented consistently.

## Implementation Notes for This Codebase

- integrate form management with the existing `Config` access model already used by `Developer` and `SuperAdmin`
- keep `Review Queue` and `My Requests` in the topbar rather than burying them under `Config`
- reuse existing notification patterns for in-app alerts
- add dedicated workflow tables rather than overloading the current legacy `buttons` table
- treat published forms as dashboard quick cards generated from form metadata and access rules

