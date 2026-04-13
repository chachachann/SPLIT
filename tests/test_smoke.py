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
            "form_preview",
            "form_home",
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


if __name__ == "__main__":
    unittest.main()
