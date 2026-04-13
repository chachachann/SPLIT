import unittest

import forms_workflow
import logic
import main
from split_app.services.chat_auth import is_chat_favorite
from split_app.routes import auth as auth_routes
from split_app.routes import chat as chat_routes
from split_app.routes import workflow as workflow_routes
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
            "chat_favorite_toggle",
            "chat_favorite_move",
            "forms_manage",
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


if __name__ == "__main__":
    unittest.main()
