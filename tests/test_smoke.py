import atexit
import os
import tempfile
import unittest

_TEST_DB_DIR = tempfile.TemporaryDirectory()
atexit.register(_TEST_DB_DIR.cleanup)
os.environ["SPLIT_DB_PATH"] = os.path.join(_TEST_DB_DIR.name, "test_smoke.sqlite3")

import forms_workflow
import logic
import main
from split_app.services.chat_auth import is_chat_favorite
from split_app.services import content as content_services
from split_app.routes import auth as auth_routes
from split_app.routes import chat as chat_routes
from split_app.routes import workflow as workflow_routes
from split_app.workflow import runtime as workflow_runtime
from split_app.workflow import smtp as workflow_smtp
from split_app.workflow import templates as workflow_templates
import split_app.support as support


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logic.init_db()
        cls._ensure_test_user("codex_target", "Codex Target")
        cls._ensure_test_user("codex_alt", "Codex Alternate")
        cls._ensure_test_user("codex_viewer", "Codex Viewer")
        cls.app = main.app

    @classmethod
    def _ensure_test_user(cls, username, fullname):
        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO users (username, password, designation, userlevel, fullname, date_created)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, logic.hash_password("password"), "Staff", "Staff", fullname, logic.timestamp_now()),
        )
        connection.commit()
        cursor.execute("SELECT id FROM users WHERE lower(username) = lower(?)", (username,))
        user_row = cursor.fetchone()
        if user_row:
            role_row = logic.fetch_role_by_name(connection, "Staff")
            if role_row:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO user_roles (user_id, role_id)
                    VALUES (?, ?)
                    """,
                    (user_row["id"], role_row["id"]),
                )
        connection.commit()
        connection.close()

    def setUp(self):
        self.client = self.app.test_client()
        connection = logic.connect_db()
        connection.execute(
            """
            DELETE FROM chat_favorites
            WHERE lower(owner_username) = lower(?)
            """,
            ("RO_Admin",),
        )
        connection.commit()
        connection.close()

    def _login_as_admin(self):
        with self.client.session_transaction() as session_data:
            session_data["user"] = "RO_Admin"
            session_data["fullname"] = "Regional Admin"
            session_data["display_name"] = "Regional Admin"
            session_data["profile_full_name"] = "Regional Admin"
            session_data["designation"] = "admin"
            session_data["avatar_url"] = ""
            session_data["avatar_initials"] = "RA"
            session_data["theme_preference"] = "dark"

    def _login_as_user(self, username, fullname):
        with self.client.session_transaction() as session_data:
            session_data["user"] = username
            session_data["fullname"] = fullname
            session_data["display_name"] = fullname
            session_data["profile_full_name"] = fullname
            session_data["designation"] = "Staff"
            session_data["avatar_url"] = ""
            session_data["avatar_initials"] = "".join(part[:1] for part in fullname.split()[:2]).upper() or "U"
            session_data["theme_preference"] = "dark"

    def test_login_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_redirects_when_logged_out(self):
        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers["Location"])

    def test_logic_facades_resolve_to_extracted_modules(self):
        self.assertEqual(logic.validate_user.__module__, "split_app.services.chat_auth")
        self.assertEqual(logic.build_profile_identity.__module__, "split_app.services.profiles")
        self.assertEqual(logic.get_news_posts.__module__, "split_app.services.content")

    def test_workflow_facades_resolve_to_extracted_modules(self):
        self.assertEqual(forms_workflow.list_forms_for_manager.__module__, "split_app.workflow.templates")
        self.assertEqual(forms_workflow.submit_submission.__module__, "split_app.workflow.runtime")
        self.assertEqual(forms_workflow.get_smtp_settings.__module__, "split_app.workflow.smtp")

    def test_route_modules_use_extracted_services(self):
        self.assertEqual(auth_routes.validate_user.__module__, "split_app.services.chat_auth")
        self.assertEqual(chat_routes.get_chat_overview.__module__, "split_app.services.chat_auth")
        self.assertEqual(chat_routes.set_chat_favorite.__module__, "split_app.services.chat_auth")
        self.assertEqual(workflow_routes.create_form_template.__module__, "split_app.workflow.templates")
        self.assertEqual(workflow_routes.submit_submission.__module__, "split_app.workflow.runtime")
        self.assertEqual(workflow_routes.get_smtp_settings.__module__, "split_app.workflow.smtp")
        self.assertEqual(support.get_form_notifications_for_user.__module__, "split_app.workflow.common")
        self.assertEqual(support.get_workflow_topbar_counts.__module__, "split_app.workflow.templates")

    def test_expected_routes_exist(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}
        for endpoint in {
            "login",
            "dashboard",
            "chat_bootstrap",
            "chat_message_update",
            "chat_message_delete",
            "chat_favorite_toggle",
            "chat_favorite_move",
            "forms_manage",
            "form_library",
            "form_case_detail",
            "form_preview",
            "form_home",
            "form_submission_archive",
            "form_submission_delete_archived",
            "form_submission_delete_pending",
            "form_submission_take",
            "form_submission_review_assignment",
            "form_submission_reopen_pool",
            "form_submission_reassign",
            "smtp_settings",
            "account_manager",
            "news_manager",
        }:
            self.assertIn(endpoint, endpoints)

    def test_chat_favorite_toggle_endpoint_adds_and_removes_favorite(self):
        self._login_as_admin()

        add_response = self.client.post(
            "/chat/favorites/toggle",
            data={"username": "codex_target", "state": "on"},
        )
        self.assertEqual(add_response.status_code, 200)
        add_payload = add_response.get_json()
        self.assertTrue(add_payload["ok"])
        self.assertTrue(is_chat_favorite("RO_Admin", "codex_target"))
        self.assertTrue(any(item["username"] == "codex_target" for item in add_payload["overview"]["favorites"]))

        remove_response = self.client.post(
            "/chat/favorites/toggle",
            data={"username": "codex_target", "state": "off"},
        )
        self.assertEqual(remove_response.status_code, 200)
        remove_payload = remove_response.get_json()
        self.assertTrue(remove_payload["ok"])
        self.assertFalse(is_chat_favorite("RO_Admin", "codex_target"))
        self.assertFalse(any(item["username"] == "codex_target" for item in remove_payload["overview"]["favorites"]))

    def test_chat_favorite_move_endpoint_reorders_favorites(self):
        self._login_as_admin()
        self.client.post("/chat/favorites/toggle", data={"username": "codex_target", "state": "on"})
        self.client.post("/chat/favorites/toggle", data={"username": "codex_alt", "state": "on"})

        move_response = self.client.post(
            "/chat/favorites/move",
            data={"username": "codex_alt", "direction": "up"},
        )
        self.assertEqual(move_response.status_code, 200)
        move_payload = move_response.get_json()
        self.assertTrue(move_payload["ok"])
        favorites = move_payload["overview"]["favorites"]
        self.assertEqual([item["username"] for item in favorites[:2]], ["codex_alt", "codex_target"])

        overview = chat_routes.get_chat_overview("RO_Admin", ["SuperAdmin"])
        self.assertEqual([item["username"] for item in overview["favorites"][:2]], ["codex_alt", "codex_target"])
        self.assertEqual([item["username"] for item in overview["users"][:2]], ["codex_alt", "codex_target"])

    def test_chat_favorite_toggle_rejects_self_favorite(self):
        self._login_as_admin()

        response = self.client.post(
            "/chat/favorites/toggle",
            data={"username": "RO_Admin", "state": "on"},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("cannot favorite yourself", payload["message"].lower())

    def test_form_library_route_is_accessible_to_logged_in_staff(self):
        self._login_as_user("codex_target", "Codex Target")
        response = self.client.get("/forms/manage/library")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Form Library", response.data)

    def test_form_library_is_filtered_to_visible_submissions(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Library Visible {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Library Visible {unique_suffix}",
            "description": "Visibility-filtered library regression form",
            "quick_label": "Visible",
            "tracking_prefix": "VISI",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": False,
            "deadline_days": "",
            "next_form_id": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": "[]",
            "quick_icon_type": "emoji",
            "quick_icon_value": "V",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        ok, message, submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Library Owner"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(submitted["status"], "completed")

        target_items = workflow_runtime.get_submission_library("codex_target", ["Staff"], status_filter="all")
        alt_items = workflow_runtime.get_submission_library("codex_alt", ["Staff"], status_filter="all")
        self.assertTrue(any(item["id"] == submission_id for item in target_items))
        self.assertFalse(any(item["id"] == submission_id for item in alt_items))

        target_cases = workflow_runtime.get_case_library("codex_target", ["Staff"], status_filter="all")
        alt_cases = workflow_runtime.get_case_library("codex_alt", ["Staff"], status_filter="all")
        self.assertTrue(any(item["primary_submission_id"] == submission_id for item in target_cases))
        self.assertFalse(any(item["primary_submission_id"] == submission_id for item in alt_cases))

    def test_library_visibility_is_separate_from_submit_access(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Library Split {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Library Split {unique_suffix}",
            "description": "Submit access stays separate from library visibility",
            "quick_label": "Split",
            "tracking_prefix": "SPLT",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": False,
            "deadline_days": "",
            "next_form_id": "",
            "assignment_review_type": "",
            "assignment_review_value": "",
            "access_roles": ["Staff"],
            "access_users": ["codex_target"],
            "library_roles": [],
            "library_users": ["codex_alt"],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": "[]",
            "promotion_rules_json": "[]",
            "quick_icon_type": "text",
            "quick_icon_value": "SP",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, _ = workflow_runtime.start_form_draft(form_key, "codex_alt", ["Staff"])
        self.assertFalse(ok)
        self.assertIn("access", message.lower())

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        ok, message, submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Split Viewer"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(submitted["status"], "completed")

        alt_cases = workflow_runtime.get_case_library("codex_alt", ["Staff"], status_filter="all")
        viewer_cases = workflow_runtime.get_case_library("codex_viewer", ["Staff"], status_filter="all")
        self.assertTrue(any(item["primary_submission_id"] == submission_id for item in alt_cases))
        self.assertFalse(any(item["primary_submission_id"] == submission_id for item in viewer_cases))

        detail_ok, detail_message, _payload = workflow_runtime.get_submission_detail_context(submission_id, "codex_alt", ["Staff"])
        self.assertTrue(detail_ok, detail_message)

    def test_private_fields_and_attachments_are_hidden_from_library_viewers(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Private Fields {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Private Fields {unique_suffix}",
            "description": "Private field masking regression form",
            "quick_label": "Private",
            "tracking_prefix": "PRIV",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": False,
            "deadline_days": "",
            "next_form_id": "",
            "assignment_review_type": "",
            "assignment_review_value": "",
            "access_roles": ["Staff"],
            "access_users": ["codex_target"],
            "library_roles": ["Staff"],
            "library_users": [],
            "schema_json": (
                '[{"label":"Public Note","key":"public_note","type":"short_text","required":true},'
                '{"label":"Secret Note","key":"secret_note","type":"short_text","required":true,"is_private":true},'
                '{"label":"Public Doc","key":"public_doc","type":"file_upload","required":false},'
                '{"label":"Secret Doc","key":"secret_doc","type":"file_upload","required":false,"is_private":true}]'
            ),
            "review_stages_json": "[]",
            "promotion_rules_json": "[]",
            "quick_icon_type": "text",
            "quick_icon_value": "PF",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        ok, message, submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {
                "field__public_note": "Visible note",
                "field__secret_note": "Private note",
            },
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(submitted["status"], "completed")

        connection = logic.connect_db()
        connection.execute(
            """
            INSERT INTO form_submission_files (
                submission_id,
                field_key,
                original_name,
                stored_name,
                file_ext,
                mime_type,
                file_size_bytes,
                file_kind,
                uploaded_by_username,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                "public_doc",
                "public.txt",
                "public.txt",
                ".txt",
                "text/plain",
                128,
                "document",
                "codex_target",
                logic.timestamp_now(),
            ),
        )
        connection.execute(
            """
            INSERT INTO form_submission_files (
                submission_id,
                field_key,
                original_name,
                stored_name,
                file_ext,
                mime_type,
                file_size_bytes,
                file_kind,
                uploaded_by_username,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                "secret_doc",
                "secret.txt",
                "secret.txt",
                ".txt",
                "text/plain",
                128,
                "document",
                "codex_target",
                logic.timestamp_now(),
            ),
        )
        connection.commit()
        connection.close()

        alt_ok, alt_message, alt_payload = workflow_runtime.get_submission_detail_context(submission_id, "codex_alt", ["Staff"])
        self.assertTrue(alt_ok, alt_message)
        alt_field_keys = {field["key"] for field in alt_payload["visible_fields"]}
        self.assertEqual({"public_note", "public_doc"}, alt_field_keys)
        self.assertFalse(alt_payload["can_view_private_fields"])
        self.assertIn("public_doc", alt_payload["file_groups"])
        self.assertNotIn("secret_doc", alt_payload["file_groups"])

        alt_cases = workflow_runtime.get_case_library("codex_alt", ["Staff"], status_filter="all")
        matching_case = next(item for item in alt_cases if item["primary_submission_id"] == submission_id)
        alt_preview_labels = {row["label"] for row in matching_case["preview_rows"]}
        self.assertIn("Public Note", alt_preview_labels)
        self.assertNotIn("Secret Note", alt_preview_labels)

        requester_ok, requester_message, requester_payload = workflow_runtime.get_submission_detail_context(submission_id, "codex_target", ["Staff"])
        self.assertTrue(requester_ok, requester_message)
        requester_field_keys = {field["key"] for field in requester_payload["visible_fields"]}
        self.assertEqual({"public_note", "secret_note", "public_doc", "secret_doc"}, requester_field_keys)
        self.assertTrue(requester_payload["can_view_private_fields"])
        self.assertIn("public_doc", requester_payload["file_groups"])
        self.assertIn("secret_doc", requester_payload["file_groups"])

    def test_reviewers_can_see_private_fields_without_library_visibility(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Reviewer Private {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Reviewer Private {unique_suffix}",
            "description": "Reviewers should see private fields",
            "quick_label": "RP",
            "tracking_prefix": "RPRI",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": True,
            "deadline_days": "",
            "next_form_id": "",
            "assignment_review_type": "",
            "assignment_review_value": "",
            "access_roles": ["Staff"],
            "access_users": ["codex_target"],
            "library_roles": [],
            "library_users": [],
            "schema_json": (
                '[{"label":"Public Note","key":"public_note","type":"short_text","required":true},'
                '{"label":"Secret Note","key":"secret_note","type":"short_text","required":true,"is_private":true}]'
            ),
            "review_stages_json": '[{"name":"Approval","mode":"parallel","reviewers":[{"type":"role","value":"Staff"}]}]',
            "promotion_rules_json": "[]",
            "quick_icon_type": "text",
            "quick_icon_value": "RV",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        ok, message, submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {
                "field__public_note": "Visible note",
                "field__secret_note": "Reviewer note",
            },
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(submitted["status"], "pending")

        reviewer_ok, reviewer_message, reviewer_payload = workflow_runtime.get_submission_detail_context(submission_id, "codex_alt", ["Staff"])
        self.assertTrue(reviewer_ok, reviewer_message)
        reviewer_field_keys = {field["key"] for field in reviewer_payload["visible_fields"]}
        self.assertEqual({"public_note", "secret_note"}, reviewer_field_keys)
        self.assertTrue(reviewer_payload["can_view_private_fields"])

    def test_create_marquee_item_rejects_duplicate_active_message(self):
        unique_message = f"codex-marquee-{logic.timestamp_now()}"
        ok, _ = content_services.create_marquee_item(unique_message)
        self.assertTrue(ok)

        duplicate_ok, duplicate_message = content_services.create_marquee_item(unique_message)
        self.assertFalse(duplicate_ok)
        self.assertIn("already exists", duplicate_message.lower())

    def test_normalize_card_accent_accepts_short_and_long_hex(self):
        self.assertEqual(workflow_templates._normalize_card_accent("#43E493"), "#43e493")
        self.assertEqual(workflow_templates._normalize_card_accent("43E493"), "#43e493")
        self.assertEqual(workflow_templates._normalize_card_accent("#4e9"), "#44ee99")
        self.assertEqual(workflow_templates._normalize_card_accent("bad-value"), "#43e493")

    def test_create_user_account_rejects_weak_password(self):
        ok, message = logic.create_user_account(
            "codex_weak",
            "weak",
            "Staff",
            ["Staff"],
            "Codex Weak",
            actor_username="RO_Admin",
        )
        self.assertFalse(ok)
        self.assertIn("at least 8 characters", message.lower())

    def test_password_request_rejects_weak_password(self):
        ok, message = logic.submit_password_change_request("RO_Admin", "weak", "weak")
        self.assertFalse(ok)
        self.assertIn("at least 8 characters", message.lower())

    def test_create_notification_rejects_invalid_link(self):
        ok, message = content_services.create_notification(
            "Codex notice",
            "Testing invalid link validation.",
            ["All"],
            "info",
            link_url="javascript:alert(1)",
            actor_username="RO_Admin",
            actor_fullname="Regional Admin",
        )
        self.assertFalse(ok)
        self.assertIn("url", message.lower())

    def test_save_smtp_settings_rejects_conflicting_tls_and_ssl(self):
        ok, message = workflow_smtp.save_smtp_settings(
            {
                "host": "smtp.example.com",
                "port": "465",
                "from_email": "admin@example.com",
                "use_tls": "1",
                "use_ssl": "1",
                "is_enabled": "1",
            },
            "RO_Admin",
        )
        self.assertFalse(ok)
        self.assertIn("either ssl or tls", message.lower())

    def test_password_change_review_approve_path_works(self):
        connection = logic.connect_db()
        connection.execute(
            """
            DELETE FROM password_change_requests
            WHERE requester_user_id = (
                SELECT id FROM users WHERE lower(username) = lower(?)
            )
            """,
            ("codex_target",),
        )
        connection.commit()
        connection.close()

        ok, message = logic.submit_password_change_request("codex_target", "StrongPass123!", "StrongPass123!")
        self.assertTrue(ok, message)

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id
            FROM password_change_requests
            WHERE status = 'pending' AND requester_user_id = (
                SELECT id FROM users WHERE lower(username) = lower(?)
            )
            ORDER BY id DESC
            LIMIT 1
            """,
            ("codex_target",),
        )
        request_row = cursor.fetchone()
        connection.close()
        self.assertIsNotNone(request_row)

        ok, message = logic.review_password_change_request(request_row["id"], "RO_Admin", ["SuperAdmin"], "approve", "")
        self.assertTrue(ok, message)
        self.assertIn("password updated", message.lower())

    def test_password_change_self_review_route_redirects_cleanly(self):
        connection = logic.connect_db()
        connection.execute(
            """
            DELETE FROM password_change_requests
            WHERE requester_user_id = (
                SELECT id FROM users WHERE lower(username) = lower(?)
            )
            """,
            ("RO_Admin",),
        )
        connection.commit()
        connection.close()

        ok, message = logic.submit_password_change_request("RO_Admin", "AdminPass123!", "AdminPass123!")
        self.assertTrue(ok, message)

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id
            FROM password_change_requests
            WHERE status = 'pending' AND requester_user_id = (
                SELECT id FROM users WHERE lower(username) = lower(?)
            )
            ORDER BY id DESC
            LIMIT 1
            """,
            ("RO_Admin",),
        )
        request_row = cursor.fetchone()
        connection.close()
        self.assertIsNotNone(request_row)

        self._login_as_admin()
        response = self.client.post(
            f"/profile/password-requests/{request_row['id']}/review",
            data={"review_action": "approve"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password updated", response.data)

    def test_chat_message_update_and_delete_endpoints(self):
        self._login_as_admin()
        send_response = self.client.post(
            "/chat/send",
            data={"type": "direct", "target": "codex_target", "message": "Codex original message"},
        )
        self.assertEqual(send_response.status_code, 200)
        send_payload = send_response.get_json()
        message_id = send_payload["messages"][-1]["id"]

        update_response = self.client.post(
            "/chat/message/update",
            data={"message_id": str(message_id), "body": "Codex edited message"},
        )
        self.assertEqual(update_response.status_code, 200)
        update_payload = self.client.get("/chat/thread?type=direct&target=codex_target").get_json()
        last_message = update_payload["messages"][-1]
        self.assertEqual(last_message["body"], "Codex edited message")
        self.assertTrue(last_message["is_edited"])

        delete_response = self.client.post(
            "/chat/message/delete",
            data={"message_id": str(message_id)},
        )
        self.assertEqual(delete_response.status_code, 200)
        delete_payload = self.client.get("/chat/thread?type=direct&target=codex_target").get_json()
        deleted_message = delete_payload["messages"][-1]
        self.assertTrue(deleted_message["is_deleted"])
        self.assertEqual(deleted_message["body"], "")

    def test_form_preview_route_renders_for_manager(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Preview {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Preview {unique_suffix}",
            "description": "Preview route regression form",
            "quick_label": "Preview",
            "tracking_prefix": "PREV",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Visit Date","key":"visit_date","type":"calendar","required":true}]',
            "review_stages_json": '[{"name":"Initial Review","mode":"sequential","reviewers":[{"type":"role","value":"Staff"}]}]',
            "quick_icon_type": "text",
            "quick_icon_value": "PV",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        self._login_as_admin()
        response = self.client.get(f"/forms/manage/{form_key}/preview")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Preview Submitted Forms", response.data)
        self.assertIn(b"Form Preview", response.data)

    def test_workflow_reuses_existing_draft_and_keeps_version_snapshot(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Draft {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Draft {unique_suffix}",
            "description": "Codex workflow duplicate-draft regression form",
            "quick_label": "Draft",
            "tracking_prefix": "DRFT",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": (
                '[{"label":"Applicant Name","key":"applicant_name","type":"short_text",'
                '"required":true,"default_value":"Preset","placeholder":"Type here"}]'
            ),
            "review_stages_json": '[{"name":"Initial Review","mode":"sequential","reviewers":[{"type":"role","value":"Staff"}]}]',
            "quick_icon_type": "text",
            "quick_icon_value": "DR",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        self.assertTrue(submission_id)

        ok, message, duplicate_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        self.assertEqual(duplicate_id, submission_id)

        updated_payload = dict(payload)
        updated_payload["schema_json"] = (
            '[{"label":"Applicant Name","key":"applicant_name","type":"short_text",'
            '"required":true,"default_value":"Preset","placeholder":"Changed placeholder"},'
            '{"label":"Visit Date","key":"visit_date","type":"calendar","required":false}]'
        )
        ok, message = workflow_templates.save_form_definition(form_key, updated_payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, context = workflow_runtime.get_submission_editor_context(submission_id, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        self.assertEqual(len(context["schema"]), 1)
        self.assertEqual(context["schema"][0]["placeholder"], "Type here")

    def test_workflow_calendar_submission_path_works(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Workflow {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Workflow {unique_suffix}",
            "description": "Codex workflow regression form",
            "quick_label": "Codex",
            "tracking_prefix": "CODEX",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": (
                '[{"label":"Applicant Name","key":"applicant_name","type":"short_text",'
                '"required":true,"default_value":"Preset","placeholder":"Type here"},'
                '{"label":"Visit Date","key":"visit_date","type":"calendar","required":true}]'
            ),
            "review_stages_json": '[{"name":"Initial Review","mode":"sequential","reviewers":[{"type":"role","value":"Staff"}]}]',
            "quick_icon_type": "text",
            "quick_icon_value": "CW",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        self.assertTrue(submission_id)

        ok, message, context = workflow_runtime.get_submission_editor_context(submission_id, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        self.assertEqual(context["schema"][1]["type"], "calendar")

        ok, message, updated = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Alice Example", "field__visit_date": "2026-04-13"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(updated["status"], "pending")
        self.assertEqual(updated["data"]["applicant_name"], "Alice Example")
        self.assertEqual(updated["data"]["visit_date"], "2026-04-13")

    def test_dashboard_forms_only_include_published_forms(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, published_form_key = workflow_templates.create_form_template(f"Codex Published {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)
        ok, message, draft_form_key = workflow_templates.create_form_template(f"Codex Draft Hidden {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        published_payload = {
            "title": f"Codex Published {unique_suffix}",
            "description": "Visible in dashboard quick access",
            "quick_label": "Published",
            "tracking_prefix": "PUBX",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": True,
            "deadline_days": "",
            "next_form_id": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": '[{"name":"Approval","mode":"parallel","reviewers":[{"type":"role","value":"Staff"}]}]',
            "quick_icon_type": "emoji",
            "quick_icon_value": "P",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(published_form_key, published_payload, "RO_Admin")
        self.assertTrue(ok, message)

        draft_payload = dict(published_payload)
        draft_payload["title"] = f"Codex Draft Hidden {unique_suffix}"
        draft_payload["quick_label"] = "Draft Hidden"
        draft_payload["tracking_prefix"] = "DRHX"
        draft_payload["status"] = "draft"
        ok, message = workflow_templates.save_form_definition(draft_form_key, draft_payload, "RO_Admin")
        self.assertTrue(ok, message)

        dashboard_forms = workflow_templates.list_dashboard_forms("codex_target", ["Staff"])
        dashboard_form_keys = {item["form_key"] for item in dashboard_forms}
        self.assertIn(published_form_key, dashboard_form_keys)
        self.assertNotIn(draft_form_key, dashboard_form_keys)

    def test_draft_form_submission_cannot_be_submitted_after_form_unpublished(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Submit Guard {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Submit Guard {unique_suffix}",
            "description": "Prevent submit when form is no longer published",
            "quick_label": "Submit Guard",
            "tracking_prefix": "SGRD",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": True,
            "deadline_days": "",
            "next_form_id": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": '[{"name":"Approval","mode":"parallel","reviewers":[{"type":"role","value":"Staff"}]}]',
            "quick_icon_type": "emoji",
            "quick_icon_value": "S",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)

        hidden_payload = dict(payload)
        hidden_payload["status"] = "draft"
        ok, message = workflow_templates.save_form_definition(form_key, hidden_payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, updated = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Blocked Submit"},
            {},
            remove_file_ids=[],
        )
        self.assertFalse(ok)
        self.assertIn("published forms", message.lower())
        self.assertIsNone(updated)

    def test_no_review_form_completes_immediately_on_submit(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Direct {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Direct {unique_suffix}",
            "description": "Direct completion regression form",
            "quick_label": "Direct",
            "tracking_prefix": "DIRX",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": False,
            "deadline_days": "5",
            "next_form_id": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": "[]",
            "quick_icon_type": "text",
            "quick_icon_value": "DX",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)

        ok, message, updated = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Immediate Finish"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(updated["status"], "completed")
        self.assertTrue(updated["submitted_at"])
        self.assertTrue(updated["completed_at"])
        self.assertTrue(updated["deadline_at"])

    def test_final_approval_promotes_to_next_form(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, next_form_key = workflow_templates.create_form_template(f"Codex Survey Status {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        next_payload = {
            "title": f"Codex Survey Status {unique_suffix}",
            "description": "Promotion target form",
            "quick_label": "Status",
            "tracking_prefix": "STAT",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": False,
            "deadline_days": "3",
            "next_form_id": "",
            "assignment_review_type": "",
            "assignment_review_value": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":false}]',
            "review_stages_json": "[]",
            "promotion_rules_json": "[]",
            "quick_icon_type": "text",
            "quick_icon_value": "ST",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(next_form_key, next_payload, "RO_Admin")
        self.assertTrue(ok, message)

        next_form = workflow_templates.get_form_template(next_form_key)
        self.assertIsNotNone(next_form)

        ok, message, source_form_key = workflow_templates.create_form_template(f"Codex Survey Request {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        source_payload = {
            "title": f"Codex Survey Request {unique_suffix}",
            "description": "Promotion source form",
            "quick_label": "Request",
            "tracking_prefix": "SURV",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": True,
            "deadline_days": "7",
            "next_form_id": "",
            "assignment_review_type": "",
            "assignment_review_value": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": '[{"name":"Initial Review","mode":"sequential","reviewers":[{"type":"role","value":"Staff"}]}]',
            "promotion_rules_json": '[{"target_form_id":' + str(next_form["id"]) + ',"spawn_mode":"automatic"}]',
            "quick_icon_type": "text",
            "quick_icon_value": "SR",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(source_form_key, source_payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(source_form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)

        ok, message, submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Promoted Applicant"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(submitted["status"], "pending")

        detail_ok, detail_message, detail_context = workflow_runtime.get_submission_detail_context(submission_id, "codex_target", ["Staff"])
        self.assertTrue(detail_ok, detail_message)
        self.assertTrue(detail_context["actionable_task_ids"])
        task_id = sorted(detail_context["actionable_task_ids"])[0]

        ok, message = workflow_runtime.review_submission_action(
            submission_id,
            task_id,
            "codex_target",
            "Codex Target",
            ["Staff"],
            "approve",
            "Approved for next stage",
        )
        self.assertTrue(ok, message)
        self.assertIn("promoted", message.lower())

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT status, promoted_to_submission_id, tracking_number, case_id
            FROM form_submissions
            WHERE id = ?
            """,
            (submission_id,),
        )
        parent_row = cursor.fetchone()
        self.assertIsNotNone(parent_row)
        self.assertEqual(parent_row["status"], "promoted")
        self.assertTrue(parent_row["promoted_to_submission_id"])

        cursor.execute(
            """
            SELECT status, parent_submission_id, tracking_number, case_id
            FROM form_submissions
            WHERE id = ?
            """,
            (parent_row["promoted_to_submission_id"],),
        )
        child_row = cursor.fetchone()
        cursor.execute("SELECT tracking_number FROM workflow_cases WHERE id = ?", (parent_row["case_id"],))
        case_row = cursor.fetchone()
        connection.close()
        self.assertIsNotNone(child_row)
        self.assertEqual(child_row["status"], "open")
        self.assertEqual(child_row["parent_submission_id"], submission_id)
        self.assertTrue(child_row["tracking_number"])
        self.assertEqual(child_row["case_id"], parent_row["case_id"])
        self.assertIsNotNone(case_row)
        self.assertEqual(case_row["tracking_number"], parent_row["tracking_number"])

        quick_items = workflow_runtime.get_quick_access_work_items("codex_target", ["Staff"])
        self.assertTrue(any(item["id"] == parent_row["promoted_to_submission_id"] for item in quick_items))

        ok, message = workflow_runtime.take_submission(parent_row["promoted_to_submission_id"], "codex_target", ["Staff"])
        self.assertTrue(ok, message)

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT status, assigned_to_username
            FROM form_submissions
            WHERE id = ?
            """,
            (parent_row["promoted_to_submission_id"],),
        )
        assigned_row = cursor.fetchone()
        connection.close()
        self.assertEqual(assigned_row["status"], "assigned")
        self.assertEqual(assigned_row["assigned_to_username"], "codex_target")

        self._login_as_user("codex_target", "Codex Target")
        response = self.client.get(f"/forms/cases/{parent_row['tracking_number']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Case Tabs", response.data)
        self.assertIn(source_payload["title"].encode("utf-8"), response.data)
        self.assertIn(next_payload["title"].encode("utf-8"), response.data)

    def test_take_form_can_require_assignment_review(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, target_form_key = workflow_templates.create_form_template(f"Codex Claim Target {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        target_payload = {
            "title": f"Codex Claim Target {unique_suffix}",
            "description": "Assignment review target form",
            "quick_label": "Claim",
            "tracking_prefix": "CLMT",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": False,
            "deadline_days": "4",
            "next_form_id": "",
            "assignment_review_type": "role",
            "assignment_review_value": "Staff",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Work Note","key":"work_note","type":"short_text","required":false}]',
            "review_stages_json": "[]",
            "promotion_rules_json": "[]",
            "quick_icon_type": "text",
            "quick_icon_value": "CT",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(target_form_key, target_payload, "RO_Admin")
        self.assertTrue(ok, message)
        target_form = workflow_templates.get_form_template(target_form_key)
        self.assertIsNotNone(target_form)

        ok, message, source_form_key = workflow_templates.create_form_template(f"Codex Claim Source {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)
        source_payload = {
            "title": f"Codex Claim Source {unique_suffix}",
            "description": "Assignment review source form",
            "quick_label": "Source",
            "tracking_prefix": "CLMS",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": True,
            "deadline_days": "5",
            "next_form_id": "",
            "assignment_review_type": "",
            "assignment_review_value": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": '[{"name":"Approval","mode":"parallel","reviewers":[{"type":"role","value":"Staff"}]}]',
            "promotion_rules_json": '[{"target_form_id":' + str(target_form["id"]) + ',"spawn_mode":"automatic"}]',
            "quick_icon_type": "text",
            "quick_icon_value": "CS",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(source_form_key, source_payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(source_form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        ok, message, submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Claim Applicant"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        detail_ok, detail_message, detail_context = workflow_runtime.get_submission_detail_context(submission_id, "codex_target", ["Staff"])
        self.assertTrue(detail_ok, detail_message)
        task_id = sorted(detail_context["actionable_task_ids"])[0]

        ok, message = workflow_runtime.review_submission_action(
            submission_id,
            task_id,
            "codex_target",
            "Codex Target",
            ["Staff"],
            "approve",
            "Approved for claim flow",
        )
        self.assertTrue(ok, message)

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT promoted_to_submission_id
            FROM form_submissions
            WHERE id = ?
            """,
            (submission_id,),
        )
        promoted_submission_id = cursor.fetchone()["promoted_to_submission_id"]
        connection.close()

        ok, message = workflow_runtime.take_submission(promoted_submission_id, "codex_alt", ["Staff"], note="Requesting assignment")
        self.assertTrue(ok, message)
        self.assertIn("assignment request", message.lower())

        queue_items = workflow_runtime.get_review_queue("RO_Admin", ["SuperAdmin"])
        self.assertTrue(any(item.get("queue_kind") == "assignment" and item["submission_id"] == promoted_submission_id for item in queue_items))

        ok, message = workflow_runtime.review_assignment_request(
            promoted_submission_id,
            "RO_Admin",
            "Regional Admin",
            ["SuperAdmin"],
            "approve",
            "Approved assignment",
        )
        self.assertTrue(ok, message)

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT status, assigned_to_username
            FROM form_submissions
            WHERE id = ?
            """,
            (promoted_submission_id,),
        )
        approved_row = cursor.fetchone()
        connection.close()
        self.assertEqual(approved_row["status"], "assigned")
        self.assertEqual(approved_row["assigned_to_username"], "codex_alt")

    def test_admin_can_delete_pending_submission(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Pending Delete {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Pending Delete {unique_suffix}",
            "description": "Pending delete regression form",
            "quick_label": "Pending Delete",
            "tracking_prefix": "PDEL",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": True,
            "deadline_days": "",
            "next_form_id": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": '[{"name":"Approval","mode":"parallel","reviewers":[{"type":"role","value":"Staff"}]}]',
            "quick_icon_type": "emoji",
            "quick_icon_value": "🗂",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)

        ok, message, submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Delete Me"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(submitted["status"], "pending")

        self._login_as_admin()
        response = self.client.post(f"/forms/submissions/{submission_id}/delete-pending", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forms/manage/library", response.headers["Location"])

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM form_submissions WHERE id = ?", (submission_id,))
        self.assertIsNone(cursor.fetchone())
        cursor.execute("SELECT id FROM form_review_tasks WHERE submission_id = ?", (submission_id,))
        self.assertIsNone(cursor.fetchone())
        connection.close()

    def test_superadmin_can_archive_and_delete_archived_submission(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Archive {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Archive {unique_suffix}",
            "description": "Archive and delete regression form",
            "quick_label": "Archive",
            "tracking_prefix": "ARCH",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": False,
            "deadline_days": "",
            "next_form_id": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": "[]",
            "quick_icon_type": "emoji",
            "quick_icon_value": "A",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        ok, message, submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Archive Me"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)
        self.assertEqual(submitted["status"], "completed")

        self._login_as_admin()
        archive_response = self.client.post(f"/forms/submissions/{submission_id}/archive", follow_redirects=False)
        self.assertEqual(archive_response.status_code, 302)
        self.assertIn("/forms/manage/library", archive_response.headers["Location"])

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute("SELECT status, archived_at FROM form_submissions WHERE id = ?", (submission_id,))
        archived_row = cursor.fetchone()
        self.assertIsNotNone(archived_row)
        self.assertEqual(archived_row["status"], "archived")
        self.assertTrue(archived_row["archived_at"])
        connection.close()

        delete_response = self.client.post(f"/forms/submissions/{submission_id}/delete-archived", follow_redirects=False)
        self.assertEqual(delete_response.status_code, 302)
        self.assertIn("/forms/manage/library", delete_response.headers["Location"])

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM form_submissions WHERE id = ?", (submission_id,))
        self.assertIsNone(cursor.fetchone())
        connection.close()

    def test_superadmin_can_force_delete_form_template_from_builder(self):
        unique_suffix = logic.timestamp_now().replace(" ", "-").replace(":", "")
        ok, message, form_key = workflow_templates.create_form_template(f"Codex Force Delete {unique_suffix}", "RO_Admin")
        self.assertTrue(ok, message)

        payload = {
            "title": f"Codex Force Delete {unique_suffix}",
            "description": "Force delete regression form",
            "quick_label": "Force",
            "tracking_prefix": "FDEL",
            "status": "published",
            "allow_cancel": True,
            "allow_multiple_active": True,
            "requires_review": False,
            "deadline_days": "",
            "next_form_id": "",
            "assignment_review_type": "",
            "assignment_review_value": "",
            "access_roles": ["Staff"],
            "access_users": [],
            "library_roles": ["Staff"],
            "library_users": [],
            "schema_json": '[{"label":"Applicant Name","key":"applicant_name","type":"short_text","required":true}]',
            "review_stages_json": "[]",
            "promotion_rules_json": "[]",
            "quick_icon_type": "text",
            "quick_icon_value": "FD",
            "card_accent": "#43e493",
            "card_tone": "mint",
        }
        ok, message = workflow_templates.save_form_definition(form_key, payload, "RO_Admin")
        self.assertTrue(ok, message)

        ok, message, submission_id = workflow_runtime.start_form_draft(form_key, "codex_target", ["Staff"])
        self.assertTrue(ok, message)
        ok, message, _submitted = workflow_runtime.submit_submission(
            submission_id,
            "codex_target",
            ["Staff"],
            {"field__applicant_name": "Delete Entire Form"},
            {},
            remove_file_ids=[],
        )
        self.assertTrue(ok, message)

        self._login_as_admin()
        response = self.client.post(
            f"/forms/manage/{form_key}",
            data={"action": "force-delete-form", "force_delete_confirm": "DELETE"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forms/manage", response.headers["Location"])

        connection = logic.connect_db()
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM forms WHERE form_key = ?", (form_key,))
        self.assertIsNone(cursor.fetchone())
        cursor.execute("SELECT id FROM form_submissions WHERE form_id IN (SELECT id FROM forms WHERE form_key = ?)", (form_key,))
        self.assertIsNone(cursor.fetchone())
        connection.close()


if __name__ == "__main__":
    unittest.main()
